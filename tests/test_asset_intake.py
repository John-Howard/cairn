import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    AssetStatus,
    AssetType,
    AuditEvent,
    EntryStatus,
    InformationAsset,
    IntakeGap,
    IntakeQuestion,
    IntakeQuestionSet,
    IntakeStatus,
    IntakeSubmission,
    LegalEntity,
    RetentionRule,
    SecurityMeasure,
)
from conftest import business_function
from test_activities import _extract_csrf, _login
from test_intake import PREVENTION, _page_csrf

ASSET_CODES = {
    "AS-A1", "AS-A2", "AS-A3",
    "AS-B1", "AS-B2", "AS-B3",
    "AS-C1", "AS-C2",
    "AS-D1", "AS-D2", "AS-D2_NAME", "AS-D3",
    "AS-E1",
    "AS-F1", "AS-F2",
}


def test_asset_questions_seeded(session):
    codes = set(
        session.scalars(
            select(IntakeQuestion.code).where(
                IntakeQuestion.question_set == IntakeQuestionSet.ASSET
            )
        )
    )
    assert codes == ASSET_CODES
    assert all(
        q.question_set == IntakeQuestionSet.ASSET
        for q in session.scalars(
            select(IntakeQuestion).where(IntakeQuestion.code.in_(ASSET_CODES))
        )
    )


def test_activity_question_set_untouched(session):
    activity_questions = session.scalars(
        select(IntakeQuestion).where(IntakeQuestion.question_set == IntakeQuestionSet.ACTIVITY)
    ).all()
    assert len(activity_questions) == 51
    assert all(q.question_set == IntakeQuestionSet.ACTIVITY for q in activity_questions)


def test_asset_depends_on_seeded(session):
    def depends_on(code):
        return session.scalars(
            select(IntakeQuestion).where(IntakeQuestion.code == code)
        ).one().depends_on

    assert depends_on("AS-C2") == {"question": "AS-C1", "in": ["yes"]}
    assert depends_on("AS-D2_NAME") == {"question": "AS-D2", "in": ["yes"]}
    assert depends_on("AS-D3") == {"question": "AS-D2", "in": ["yes"]}


def _start_asset(client, engine, *, name="HR system", function=PREVENTION) -> str:
    token = _page_csrf(client, "/intake/assets/new")
    with Session(engine) as db:
        function_id = business_function(db, function).id
    response = client.post(
        "/intake/assets",
        data={
            "csrf_token": token,
            "subject_name": name,
            "business_function_id": function_id,
            "respondent_contact": "Jo Bloggs, HR admin",
        },
    )
    assert response.status_code == 302, response.text
    return response.headers["location"].split("/")[2]


def _save_section(client, submission_id: str, section: str, data: dict):
    token = _page_csrf(client, f"/intake/{submission_id}/section/{section}")
    response = client.post(
        f"/intake/{submission_id}/section/{section}",
        data={"csrf_token": token, "nav": "next", **data},
    )
    assert response.status_code == 302, response.text
    return response


def _submit(client, submission_id: str):
    token = _page_csrf(client, f"/intake/{submission_id}/review")
    response = client.post(f"/intake/{submission_id}/submit", data={"csrf_token": token})
    assert response.status_code == 302, response.text
    return response.headers["location"].split("/")[-1]


def test_asset_start_route_not_swallowed_by_submission_route(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    response = client.get("/intake/assets/new")
    assert response.status_code == 200
    assert "Give this asset a short name" in response.text


def test_asset_submission_sections_are_a_to_f(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine)
    with Session(engine) as db:
        submission = db.get(IntakeSubmission, submission_id)
        assert submission.question_set == IntakeQuestionSet.ASSET
    assert client.get(f"/intake/{submission_id}/section/A").status_code == 200
    assert client.get(f"/intake/{submission_id}/section/F").status_code == 200
    assert client.get(f"/intake/{submission_id}/section/G").status_code == 404
    assert client.get(f"/intake/{submission_id}/section/K").status_code == 404


def test_enforcement_function_asset_run_has_no_section_k(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Ollie OtherFunction")
    submission_id = _start_asset(
        client, engine, name="Enforcement case system",
        function="Protection (Fire Safety Regulation & Enforcement)",
    )
    assert client.get(f"/intake/{submission_id}/section/K").status_code == 404


def test_activity_c4_c5_validation_still_fires(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    from test_intake import _start as start_activity

    submission_id = start_activity(client, engine)
    token = _page_csrf(client, f"/intake/{submission_id}/section/C")
    response = client.post(
        f"/intake/{submission_id}/section/C",
        data={"csrf_token": token, "nav": "next", "C4": "yes", "C5": "yes"},
    )
    assert response.status_code == 422


def test_asset_similar_fragment(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    with Session(engine) as db:
        db.add_all(
            [
                InformationAsset(label="HR System", asset_type=AssetType.SYSTEM),
                InformationAsset(
                    label="HR Reporting Tool",
                    asset_type=AssetType.SYSTEM,
                    entry_status=EntryStatus.PROPOSED,
                ),
                InformationAsset(
                    label="HR Archive (rejected)",
                    asset_type=AssetType.SYSTEM,
                    entry_status=EntryStatus.REJECTED,
                ),
                InformationAsset(label="Payroll System", asset_type=AssetType.SYSTEM),
            ]
        )
        db.commit()
    _login(client, engine, "Cody Contributor")
    response = client.get("/intake/assets/similar", params={"subject_name": "hr"})
    assert response.status_code == 200
    assert "HR System" in response.text
    assert "HR Reporting Tool" in response.text
    assert "proposed" in response.text.lower()
    assert "rejected" not in response.text.lower()
    assert "Payroll" not in response.text

    short = client.get("/intake/assets/similar", params={"subject_name": "h"})
    assert short.status_code == 200
    assert "HR System" not in short.text

    none_match = client.get("/intake/assets/similar", params={"subject_name": "zzz"})
    assert none_match.status_code == 200
    assert "HR System" not in none_match.text


def test_asset_similar_caps_at_five(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    with Session(engine) as db:
        db.add_all(
            InformationAsset(label=f"Widget system {i}", asset_type=AssetType.SYSTEM)
            for i in range(7)
        )
        db.commit()
    _login(client, engine, "Cody Contributor")
    response = client.get("/intake/assets/similar", params={"subject_name": "widget"})
    assert response.text.count("Widget system") == 5


def test_asset_similar_requires_intake_role(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Vic Viewer")
    assert client.get("/intake/assets/similar", params={"subject_name": "hr"}).status_code == 403


def test_asset_similar_wiring_matches_the_start_screen_input(
    activities_client, activities_web_engine
):
    """htmx sends the input's own name as the query parameter, so the endpoint's
    parameter must match the field it is wired to — otherwise the hint silently
    never fires in a browser while direct calls still pass."""
    client, engine = activities_client, activities_web_engine
    with Session(engine) as db:
        db.add(InformationAsset(label="HR System", asset_type=AssetType.SYSTEM))
        db.commit()
    _login(client, engine, "Cody Contributor")
    page = client.get("/intake/assets/new").text

    hx_get = re.search(r'hx-get="([^"]+)"', page).group(1)
    field_name = re.search(r'id="subject_name" name="([^"]+)"', page).group(1)

    response = client.get(hx_get, params={field_name: "hr"})
    assert response.status_code == 200
    assert "HR System" in response.text


def _full_asset_run(client, engine, *, name="HR system", function=PREVENTION) -> tuple[str, str]:
    submission_id = _start_asset(client, engine, name=name, function=function)
    _save_section(
        client, submission_id, "A",
        {"AS-A1": "system", "AS-A2": "Holds staff records for HR admin.", "AS-A3": "in_use"},
    )
    _save_section(
        client, submission_id, "B",
        {
            "AS-B1": "HR admin team", "AS-B2": "Jo Smith, HR manager",
            "AS-B3": "Finance & Procurement; Some Made Up Team",
        },
    )
    _save_section(
        client, submission_id, "C",
        {"AS-C1": "yes", "AS-C2": "Names, contact details, salary."},
    )
    _save_section(
        client, submission_id, "D",
        {
            "AS-D1": "Cloud-hosted", "AS-D2": "yes",
            "AS-D2_NAME": "Acme Cloud Ltd", "AS-D3": "Ireland",
        },
    )
    _save_section(client, submission_id, "E", {"AS-E1__new": "Access controls; New Measure X"})
    _save_section(
        client, submission_id, "F",
        {"AS-F1": "7 years", "AS-F2": "2027-01-01"},
    )
    asset_id = _submit(client, submission_id)
    return submission_id, asset_id


def test_asset_intake_round_trip(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    with Session(engine) as db:
        db.add_all(
            [
                LegalEntity(label="Acme Cloud Ltd", role_type="data_supplier"),
                RetentionRule(label="7 years", period="7 years", trigger="end of employment"),
                SecurityMeasure(label="Access controls", category="organisational"),
            ]
        )
        db.commit()

    submission_id, asset_id = _full_asset_run(client, engine)

    with Session(engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.PROPOSED
        assert asset.label == "HR system"
        assert asset.asset_type == AssetType.SYSTEM
        assert asset.description == "Holds staff records for HR admin."
        assert asset.status == AssetStatus.IN_USE
        assert asset.custodian == "HR admin team"
        assert asset.contains_personal_data is True
        assert asset.location == "Cloud-hosted"
        assert asset.hosting_country == "Ireland"
        assert asset.next_review_date.isoformat() == "2027-01-01"

        bf_labels = {bf.label for bf in asset.business_functions}
        assert bf_labels == {PREVENTION, "Finance & Procurement"}
        assert "Some Made Up Team" in asset.notes

        supplier = db.scalars(
            select(LegalEntity).where(LegalEntity.label == "Acme Cloud Ltd")
        ).one()
        assert asset.supplier_entity_id == supplier.id

        retention = db.scalars(select(RetentionRule).where(RetentionRule.label == "7 years")).one()
        assert asset.default_retention_id == retention.id

        measure_labels = {m.label for m in asset.security_measures}
        assert "Access controls" in measure_labels
        assert "New Measure X" in measure_labels
        new_measure = db.scalars(
            select(SecurityMeasure).where(SecurityMeasure.label == "New Measure X")
        ).one()
        assert new_measure.entry_status == EntryStatus.PROPOSED

        assert "Jo Smith, HR manager" in asset.notes
        assert "Names, contact details, salary." in asset.notes

        gaps = db.scalars(select(IntakeGap).where(IntakeGap.submission_id == submission_id)).all()
        gap_codes = {g.question_code for g in gaps}
        assert "AS-B2" in gap_codes
        assert "AS-B3" in gap_codes
        assert all(g.asset_id == asset_id for g in gaps)

        submission = db.get(IntakeSubmission, submission_id)
        assert submission.status == IntakeStatus.SUBMITTED
        assert submission.asset_id == asset_id


def test_asset_intake_sparse_run_produces_proposed_asset_with_gaps(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Mystery cabinet")
    _save_section(client, submission_id, "A", {"AS-A1__dk": "1", "AS-A3__dk": "1"})
    _save_section(client, submission_id, "B", {"AS-B2__dk": "1"})
    _save_section(client, submission_id, "C", {"AS-C1__dk": "1"})
    asset_id = _submit(client, submission_id)
    with Session(engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.PROPOSED
        assert asset.label == "Mystery cabinet"
        gaps = db.scalars(select(IntakeGap).where(IntakeGap.submission_id == submission_id)).all()
        assert gaps
        assert all(g.asset_id == asset_id for g in gaps)
        # AS-B2 don't-know should only record one gap, not two
        b2_gaps = [g for g in gaps if g.question_code == "AS-B2"]
        assert len(b2_gaps) == 1


def test_unmatched_supplier_and_retention_recorded_as_notes_and_gap(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Odd system")
    _save_section(
        client, submission_id, "D",
        {"AS-D1": "Somewhere", "AS-D2": "yes", "AS-D2_NAME": "Nonexistent Supplier Co"},
    )
    _save_section(client, submission_id, "F", {"AS-F1": "Unknown retention rule name"})
    asset_id = _submit(client, submission_id)
    with Session(engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.supplier_entity_id is None
        assert asset.default_retention_id is None
        assert "Nonexistent Supplier Co" in asset.notes
        assert "Unknown retention rule name" in asset.notes
        gaps = db.scalars(select(IntakeGap).where(IntakeGap.submission_id == submission_id)).all()
        gap_codes = {g.question_code for g in gaps}
        assert "AS-D2_NAME" in gap_codes
        assert "AS-F1" in gap_codes


def test_asset_review_page_shows_security_measure_proposals(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Reviewed asset")
    _save_section(client, submission_id, "E", {"AS-E1__new": "Brand New Control"})
    page = client.get(f"/intake/{submission_id}/review").text
    assert "Brand New Control" in page


def test_intake_list_shows_both_sets(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    from test_intake import _start as start_activity

    start_activity(client, engine, name="An activity run")
    _start_asset(client, engine, name="An asset run")
    page = client.get("/intake").text
    assert "An activity run" in page
    assert "An asset run" in page
    assert "Activity" in page
    assert "Asset" in page


def test_gaps_queue_handles_asset_gap_without_crashing(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Gappy asset")
    _save_section(client, submission_id, "C", {"AS-C1__dk": "1"})
    _submit(client, submission_id)

    _login(client, engine, "Cara Curator")
    response = client.get("/intake/gaps")
    assert response.status_code == 200


def test_gaps_queue_links_asset_gap_to_the_asset(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Linked asset")
    _save_section(client, submission_id, "C", {"AS-C1__dk": "1"})
    asset_id = _submit(client, submission_id)

    _login(client, engine, "Cara Curator")
    page = client.get("/intake/gaps").text
    assert f"/assets/{asset_id}" in page
    assert f"/activities/{asset_id}" not in page
    assert "Asset" in page


def test_gaps_queue_intro_covers_both_records(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    page = activities_client.get("/intake/gaps").text
    assert "proposed asset" in page.lower()


def _submission_with_asset_gap(
    client, engine, *, name="Gappy asset for resolve"
) -> tuple[str, str]:
    submission_id = _start_asset(client, engine, name=name)
    _save_section(client, submission_id, "C", {"AS-C1__dk": "1"})
    asset_id = _submit(client, submission_id)
    return submission_id, asset_id


def test_resolve_and_reopen_asset_gap(activities_client, activities_web_engine):
    """The 2i.3 gate: gap resolve/reopen working against an asset, not just an
    activity — the routes are set-agnostic, so this is the proof."""
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id, _asset_id = _submission_with_asset_gap(client, engine)

    _login(client, engine, "Cara Curator")
    page = client.get("/intake/gaps")
    token = _extract_csrf(page.text)
    with Session(engine) as db:
        gap = db.scalars(
            select(IntakeGap).where(
                IntakeGap.submission_id == submission_id,
                IntakeGap.question_code == "AS-C1",
            )
        ).one()
        gap_id = gap.id

    response = client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={
            "csrf_token": token,
            "resolution_note": "Confirmed by interview: holds staff records.",
        },
    )
    assert response.status_code == 302
    with Session(engine) as db:
        gap = db.get(IntakeGap, gap_id)
        assert gap.resolved
        assert "Confirmed by interview" in gap.resolution_note
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == gap_id,
                AuditEvent.event == "intake_gap_resolved",
            )
        ).all()
        assert len(events) == 1

    response = client.post(f"/intake/gaps/{gap_id}/reopen", data={"csrf_token": token})
    assert response.status_code == 302
    with Session(engine) as db:
        gap = db.get(IntakeGap, gap_id)
        assert not gap.resolved
        assert gap.resolution_note is None
        assert (
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_id == gap_id,
                    AuditEvent.event == "intake_gap_reopened",
                )
            ).one()
            is not None
        )


def test_asset_detail_shows_intake_section_with_answer_and_open_gap(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start_asset(client, engine, name="Intake sourced asset")
    _save_section(client, submission_id, "B", {"AS-B1": "HR admin team", "AS-B2__dk": "1"})
    asset_id = _submit(client, submission_id)

    _login(client, engine, "Cara Curator")
    page = client.get(f"/assets/{asset_id}").text
    assert "Created from intake" in page
    assert "Cody Contributor" in page
    assert "HR admin team" in page
    assert "AS-B2" in page
    assert f"/intake/{submission_id}" in page


def test_asset_detail_no_intake_section_for_manually_created_asset(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    with Session(engine) as db:
        asset = InformationAsset(label="Manually added asset", asset_type=AssetType.SYSTEM)
        db.add(asset)
        db.commit()
        asset_id = asset.id

    _login(client, engine, "Cara Curator")
    page = client.get(f"/assets/{asset_id}").text
    assert "Created from intake" not in page
