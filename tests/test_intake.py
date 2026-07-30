from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    AssetType,
    AuditEvent,
    ControllerOrProcessor,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataUseMode,
    InformationAsset,
    IntakeAnswerKind,
    IntakeGap,
    IntakeQuestion,
    IntakeQuestionSet,
    IntakeStatus,
    IntakeSubmission,
    LifecycleStage,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecordStatus,
    Regime,
)
from conftest import business_function
from test_activities import _extract_csrf, _login

PREVENTION = "Prevention & Community Safety"
PROTECTION = "Protection (Fire Safety Regulation & Enforcement)"


def _page_csrf(client, url: str) -> str:
    response = client.get(url)
    assert response.status_code == 200, response.text
    return _extract_csrf(response.text)


def _start(client, engine, *, name="Home fire safety visits", function=PREVENTION) -> str:
    token = _page_csrf(client, "/intake/new")
    with Session(engine) as db:
        function_id = business_function(db, function).id
    response = client.post(
        "/intake",
        data={
            "csrf_token": token,
            "subject_name": name,
            "business_function_id": function_id,
            "respondent_contact": "Jo Bloggs, watch manager, jo@example.org",
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
    response = client.post(
        f"/intake/{submission_id}/submit", data={"csrf_token": token}
    )
    assert response.status_code == 302, response.text
    return response.headers["location"].split("/")[-1]


def _vocab_id(engine, model, label: str, attr: str = "label") -> str:
    with Session(engine) as db:
        return db.scalars(select(model).where(getattr(model, attr) == label)).one().id


def test_questions_seeded(session):
    codes = set(session.scalars(select(IntakeQuestion.code)))
    assert {"B3", "C1", "D1", "E2", "F3", "G1", "H1", "K2"} <= codes
    k = session.scalars(select(IntakeQuestion).where(IntakeQuestion.section == "K")).all()
    assert k and all(q.enforcement_only for q in k)


def test_activity_questions_default_to_activity_question_set(session):
    questions = session.scalars(
        select(IntakeQuestion).where(IntakeQuestion.question_set == IntakeQuestionSet.ACTIVITY)
    ).all()
    assert questions
    assert all(q.question_set == IntakeQuestionSet.ACTIVITY for q in questions)


def test_submission_subject_name_and_question_set_default(session, actor):
    submission = IntakeSubmission(
        subject_name="Home fire safety visits",
        business_function_id=business_function(session, PREVENTION).id,
        respondent_id=actor.id,
        answers={},
    )
    session.add(submission)
    session.flush()
    assert submission.subject_name == "Home fire safety visits"
    assert submission.question_set == IntakeQuestionSet.ACTIVITY
    assert submission.asset_id is None


def test_submission_asset_id_settable(session, actor):
    asset = InformationAsset(label="HR system", asset_type=AssetType.SYSTEM)
    session.add(asset)
    session.flush()
    submission = IntakeSubmission(
        subject_name="HR system",
        business_function_id=business_function(session, PREVENTION).id,
        respondent_id=actor.id,
        answers={},
        question_set=IntakeQuestionSet.ASSET,
        asset_id=asset.id,
    )
    session.add(submission)
    session.flush()
    assert submission.asset_id == asset.id
    assert submission.question_set == IntakeQuestionSet.ASSET


def test_gap_asset_id_nullable_and_settable(session, actor):
    asset = InformationAsset(label="Payroll system", asset_type=AssetType.SYSTEM)
    session.add(asset)
    session.flush()
    submission = IntakeSubmission(
        subject_name="Payroll system",
        business_function_id=business_function(session, PREVENTION).id,
        respondent_id=actor.id,
        answers={},
    )
    session.add(submission)
    session.flush()
    gap = IntakeGap(
        submission_id=submission.id,
        question_code="AS-B2",
        question_text="Who is the senior person responsible for it?",
    )
    session.add(gap)
    session.flush()
    assert gap.asset_id is None
    gap.asset_id = asset.id
    session.flush()
    assert gap.asset_id == asset.id


def test_viewer_cannot_use_intake(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    assert activities_client.get("/intake").status_code == 403


def test_full_intake_creates_draft_activity(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine)

    subjects_id = _vocab_id(
        engine, DataSubjectCategory, "vulnerable persons (HFSV / Safe & Well)"
    )
    health_id = _vocab_id(engine, PersonalDataCategory, "health data (casualty, OH, EMR)")
    contact_id = _vocab_id(engine, PersonalDataCategory, "contact details")
    police_id = _vocab_id(engine, Recipient, "police")

    _save_section(client, submission_id, "B", {"B3": "no"})
    _save_section(
        client,
        submission_id,
        "C",
        {
            "C1": "Visit homes to fit alarms and advise on fire risk.",
            "C3": "yes",
            "C3_DETAIL": "Fire and Rescue Services Act 2004",
            "C4": "no",
            "C5": "no",
        },
    )
    _save_section(
        client,
        submission_id,
        "D",
        {
            "D1": [subjects_id],
            "D1__new": "hoarders referred by partners",
            "D2": "yes",
            "D3": "yes",
            "D4": "hundreds",
        },
    )
    _save_section(
        client,
        submission_id,
        "E",
        {"E1": [contact_id], "E2": [health_id], "E3": "no", "E4": "More detail held for children."},
    )
    _save_section(
        client,
        submission_id,
        "F",
        {
            "F1": ["from_data_subject", "from_third_party"],
            "F2__new": "CACI Acorn",
            "F3": "yes",
            "F4": "person",
        },
    )
    _save_section(client, submission_id, "G", {"G1": [police_id], "G3": "no"})
    _save_section(
        client, submission_id, "H", {"H1__new": "HFSV mobile app", "H3__dk": "1"}
    )
    _save_section(client, submission_id, "I", {"I1": "Prevention team only"})
    _save_section(client, submission_id, "J", {"J1": "yes", "J5__dk": "1"})

    activity_id = _submit(client, submission_id)

    with Session(engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status == RecordStatus.DRAFT
        assert activity.regime == Regime.GENERAL
        assert activity.lifecycle_stage == LifecycleStage.LIVE
        assert activity.controller_or_processor == ControllerOrProcessor.CONTROLLER
        assert activity.is_statutory_task
        assert activity.children_flag
        assert activity.vulnerable_or_safeguarding_flag
        assert activity.external_data_use_mode == ExternalDataUseMode.MANUAL
        assert sorted(activity.personal_data_source) == ["from_data_subject", "from_third_party"]

        subject_labels = {s.label for s in activity.data_subjects}
        assert "vulnerable persons (HFSV / Safe & Well)" in subject_labels
        assert "hoarders referred by partners" in subject_labels
        category_labels = {c.label for c in activity.data_categories}
        assert {"contact details", "health data (casualty, OH, EMR)"} <= category_labels
        assert activity.special_category_flag
        assert not activity.criminal_offence_flag
        assert {r.label for r in activity.recipients} == {"police"}
        assert {s.name for s in activity.data_sources} == {"CACI Acorn"}
        assert {s.label for s in activity.assets} == {"HFSV mobile app"}

        proposed_system = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "HFSV mobile app")
        ).one()
        assert proposed_system.entry_status == EntryStatus.PROPOSED
        assert proposed_system.asset_type == AssetType.SYSTEM
        assert proposed_system.contains_personal_data is True

        submission = db.get(IntakeSubmission, submission_id)
        assert submission.status == IntakeStatus.SUBMITTED
        assert submission.activity_id == activity_id

        gaps = db.scalars(
            select(IntakeGap).where(IntakeGap.submission_id == submission_id)
        ).all()
        assert {g.question_code for g in gaps} == {"H3", "J5"}
        assert all(g.activity_id == activity_id and not g.resolved for g in gaps)

        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == submission_id,
                AuditEvent.event == "intake_submitted",
            )
        ).all()
        assert len(events) == 1
        assert events[0].new_value["activity"] == activity_id


def test_section_k_only_for_enforcement_functions(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    prevention_submission = _start(client, engine)
    review_needs = client.get(f"/intake/{prevention_submission}/section/K")
    assert review_needs.status_code == 404

    _login(client, engine, "Ollie OtherFunction")
    protection_submission = _start(
        client, engine, name="Fire safety audits", function=PROTECTION
    )
    assert client.get(f"/intake/{protection_submission}/section/K").status_code == 200


def test_enforcement_answers_map_to_le_fields(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Ollie OtherFunction")
    submission_id = _start(client, engine, name="Prosecuting FSO breaches", function=PROTECTION)
    _save_section(
        client, submission_id, "C", {"C1": "Investigate and prosecute FSO breaches."}
    )
    _save_section(client, submission_id, "E", {"E3": "yes"})
    _save_section(
        client,
        submission_id,
        "K",
        {"K1": "yes", "K2": ["suspect", "witness"], "K3": "yes", "K4": "Case system logs access."},
    )
    activity_id = _submit(client, submission_id)
    with Session(engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.le_data_subject_classification == ["suspect", "witness"]
        assert activity.le_fact_vs_assessment_noted is True
        assert activity.s62_logging_note == "Case system logs access."
        assert activity.criminal_offence_flag


def test_contributor_locked_to_own_function_and_own_submissions(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    token = _page_csrf(client, "/intake/new")
    with Session(engine) as db:
        protection_id = business_function(db, PROTECTION).id
    response = client.post(
        "/intake",
        data={
            "csrf_token": token,
            "subject_name": "Sneaky cross-function intake",
            "business_function_id": protection_id,
        },
    )
    assert response.status_code == 302
    submission_id = response.headers["location"].split("/")[2]
    with Session(engine) as db:
        submission = db.get(IntakeSubmission, submission_id)
        assert submission.business_function.label == PREVENTION

    _login(client, engine, "Ollie OtherFunction")
    assert client.get(f"/intake/{submission_id}/section/B").status_code == 403
    assert f"/intake/{submission_id}" not in client.get("/intake").text

    _login(client, engine, "Cara Curator")
    assert f"/intake/{submission_id}" in client.get("/intake").text


def test_purpose_dont_know_recorded_as_gap_with_placeholder(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Community events mailing list")
    _save_section(client, submission_id, "C", {"C1__dk": "1"})
    activity_id = _submit(client, submission_id)
    with Session(engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert "intake gaps" in activity.purpose
        gap_codes = {
            g.question_code
            for g in db.scalars(
                select(IntakeGap).where(IntakeGap.submission_id == submission_id)
            )
        }
        assert "C1" in gap_codes


def test_cancel_and_resubmit_guards(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Cancelled thing")
    token = _page_csrf(client, f"/intake/{submission_id}/section/B")
    response = client.post(
        f"/intake/{submission_id}/cancel", data={"csrf_token": token}
    )
    assert response.status_code == 302
    with Session(engine) as db:
        assert db.get(IntakeSubmission, submission_id).status == IntakeStatus.CANCELLED
    assert client.get(f"/intake/{submission_id}/section/B").status_code == 422
    response = client.post(
        f"/intake/{submission_id}/submit", data={"csrf_token": token}
    )
    assert response.status_code == 422


def _submission_with_gaps(client, engine, *, name="Gappy activity") -> tuple[str, str]:
    """Create and submit an intake with two don't-know answers; return (submission, activity)."""
    submission_id = _start(client, engine, name=name)
    _save_section(client, submission_id, "C", {"C1": "A purpose.", "C3__dk": "1"})
    _save_section(client, submission_id, "H", {"H3__dk": "1"})
    activity_id = _submit(client, submission_id)
    return submission_id, activity_id


def test_gaps_queue_requires_curator(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    assert client.get("/intake/gaps").status_code == 403
    _login(client, engine, "Cara Curator")
    assert client.get("/intake/gaps").status_code == 200


def test_resolve_and_reopen_gap(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id, activity_id = _submission_with_gaps(client, engine)

    _login(client, engine, "Cara Curator")
    page = client.get("/intake/gaps")
    assert "Gappy activity" in page.text
    assert "C3" in page.text and "H3" in page.text
    token = _extract_csrf(page.text)

    with Session(engine) as db:
        gap = db.scalars(
            select(IntakeGap).where(
                IntakeGap.submission_id == submission_id,
                IntakeGap.question_code == "C3",
            )
        ).one()
        gap_id = gap.id

    # Resolving without a note is rejected
    response = client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={"csrf_token": token, "resolution_note": "  "},
    )
    assert response.status_code == 422

    response = client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={
            "csrf_token": token,
            "resolution_note": "Interview 21/07: FRSA 2004 s6 duty confirmed by legal.",
        },
    )
    assert response.status_code == 302
    with Session(engine) as db:
        gap = db.get(IntakeGap, gap_id)
        assert gap.resolved
        assert "FRSA 2004" in gap.resolution_note
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == gap_id,
                AuditEvent.event == "intake_gap_resolved",
            )
        ).all()
        assert len(events) == 1
        assert "FRSA 2004" in events[0].reason

    # Resolved gap shows in the resolved table, open queue shrinks; double-resolve blocked
    page = client.get("/intake/gaps")
    assert "FRSA 2004 s6 duty confirmed" in page.text
    response = client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={"csrf_token": token, "resolution_note": "again"},
    )
    assert response.status_code == 422

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


def test_contributor_cannot_resolve_gaps(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id, _activity_id = _submission_with_gaps(
        client, engine, name="Contributor-owned gaps"
    )
    with Session(engine) as db:
        gap_id = db.scalars(
            select(IntakeGap).where(IntakeGap.submission_id == submission_id)
        ).first().id
    token = _page_csrf(client, "/intake")
    response = client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={"csrf_token": token, "resolution_note": "sneaky self-resolution"},
    )
    assert response.status_code == 403


def test_submission_view_shows_gap_status(activities_client, activities_web_engine):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id, _activity_id = _submission_with_gaps(client, engine, name="Status check")
    _login(client, engine, "Cara Curator")
    token = _page_csrf(client, "/intake/gaps")
    with Session(engine) as db:
        gap_id = db.scalars(
            select(IntakeGap).where(
                IntakeGap.submission_id == submission_id,
                IntakeGap.question_code == "H3",
            )
        ).one().id
    client.post(
        f"/intake/gaps/{gap_id}/resolve",
        data={"csrf_token": token, "resolution_note": "Retention is 6 years per policy DP-4."},
    )
    page = client.get(f"/intake/{submission_id}")
    assert "Resolved" in page.text and "Open" in page.text
    assert "Retention is 6 years per policy DP-4." in page.text


def test_existing_label_in_new_box_links_instead_of_proposing(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Referrals handling")
    _save_section(client, submission_id, "G", {"G1__new": "Police; Victim Support"})
    activity_id = _submit(client, submission_id)
    with Session(engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        labels = {r.label for r in activity.recipients}
        assert labels == {"police", "Victim Support"}
        proposed = db.scalars(
            select(Recipient).where(Recipient.label == "Victim Support")
        ).one()
        assert proposed.entry_status == EntryStatus.PROPOSED
        existing = db.scalars(select(Recipient).where(Recipient.label == "police")).all()
        assert len(existing) == 1


def test_depends_on_seeded(session):
    q = session.scalars(
        select(IntakeQuestion).where(IntakeQuestion.code == "B3_START")
    ).one()
    assert q.depends_on == {"question": "B3", "in": ["yes"]}
    j2 = session.scalars(select(IntakeQuestion).where(IntakeQuestion.code == "J2")).one()
    assert {"question": "D2", "in": ["yes"]} in j2.depends_on["all"]


def test_dependent_question_rendered_as_conditional_reveal(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Reveal check")
    page = client.get(f"/intake/{submission_id}/section/B").text
    assert 'data-aria-controls="conditional-B3-yes"' in page
    assert 'id="conditional-B3-yes"' in page
    # the dates live inside the reveal, hidden until B3=yes is chosen
    reveal = page.split('id="conditional-B3-yes"')[1]
    assert 'name="B3_START"' in reveal
    assert "govuk-radios__conditional--hidden" in page


def test_unmet_dependency_normalised_to_not_applicable(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Trial dates ignored")
    # Browser submits hidden revealed fields — B3=no must void the dates
    _save_section(
        client, submission_id, "B",
        {"B3": "no", "B3_START": "2026-01-01", "B3_END": "2026-06-30"},
    )
    activity_id = _submit(client, submission_id)
    with Session(engine) as db:
        submission = db.get(IntakeSubmission, submission_id)
        assert submission.answers["B3_START"] == {"na": True}
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.lifecycle_stage == LifecycleStage.LIVE
        assert activity.trial_start is None and activity.trial_end is None


def test_changing_parent_voids_stale_child_answers(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Stale child")
    _save_section(client, submission_id, "F", {"F3": "yes", "F4": "system", "F5": "decides"})
    # Respondent goes back and changes their mind: F3 no
    _save_section(client, submission_id, "F", {"F3": "no", "F4": "system", "F5": "decides"})
    activity_id = _submit(client, submission_id)
    with Session(engine) as db:
        submission = db.get(IntakeSubmission, submission_id)
        assert submission.answers["F4"] == {"na": True}
        assert submission.answers["F5"] == {"na": True}
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.external_data_use_mode == ExternalDataUseMode.NONE


def test_cross_section_dependency_gates_rendering(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="No children no J2")
    _save_section(client, submission_id, "D", {"D2": "no"})
    page = client.get(f"/intake/{submission_id}/section/J").text
    assert 'name="J2"' not in page

    _save_section(client, submission_id, "D", {"D2": "yes"})
    page = client.get(f"/intake/{submission_id}/section/J").text
    assert 'name="J2"' in page


def test_contradictory_c4_c5_rejected_with_error_summary(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="Contradiction")
    token = _page_csrf(client, f"/intake/{submission_id}/section/C")
    response = client.post(
        f"/intake/{submission_id}/section/C",
        data={"csrf_token": token, "nav": "next", "C4": "yes", "C5": "yes"},
    )
    assert response.status_code == 422
    assert "There is a problem" in response.text
    assert "it can&#39;t be both" in response.text or "can't be both" in response.text
    with Session(engine) as db:
        submission = db.get(IntakeSubmission, submission_id)
        assert submission.answers.get("C4") is None  # nothing saved

    # Resolving the contradiction saves normally
    response = client.post(
        f"/intake/{submission_id}/section/C",
        data={"csrf_token": token, "nav": "next", "C4": "yes", "C5": "no"},
    )
    assert response.status_code == 302


def test_dont_know_on_unasked_question_creates_no_gap(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="No phantom gaps")
    # C3 answered No; C3_DETAIL dk ticked (hidden field submitted anyway)
    _save_section(client, submission_id, "C", {"C3": "no", "C3_DETAIL__dk": "1"})
    _submit(client, submission_id)
    with Session(engine) as db:
        gap_codes = {
            g.question_code
            for g in db.scalars(
                select(IntakeGap).where(IntakeGap.submission_id == submission_id)
            )
        }
        assert "C3_DETAIL" not in gap_codes


def test_review_shows_not_applicable_for_unasked_questions(
    activities_client, activities_web_engine
):
    client, engine = activities_client, activities_web_engine
    _login(client, engine, "Cody Contributor")
    submission_id = _start(client, engine, name="NA on review")
    _save_section(client, submission_id, "B", {"B3": "no"})
    page = client.get(f"/intake/{submission_id}/review").text
    assert "Not applicable" in page


def test_seed_activity_questions_is_idempotent(session):
    from cairn.seeds.intake import seed_activity_questions

    before = session.scalars(
        select(IntakeQuestion.code).where(IntakeQuestion.question_set == IntakeQuestionSet.ACTIVITY)
    ).all()
    seed_activity_questions(session)
    after = session.scalars(
        select(IntakeQuestion.code).where(IntakeQuestion.question_set == IntakeQuestionSet.ACTIVITY)
    ).all()
    assert sorted(before) == sorted(after)


def test_seed_question_set_not_blocked_by_other_populated_set():
    from sqlalchemy import create_engine

    from cairn.models import Base
    from cairn.seeds.intake import seed_activity_questions, seed_question_set

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as fresh_session:
        seed_activity_questions(fresh_session)
        assert fresh_session.scalars(
            select(IntakeQuestion).where(IntakeQuestion.question_set == IntakeQuestionSet.ACTIVITY)
        ).first() is not None

        minimal = [
            ("AS-TEST1", "A", "What it is", "Which of these best describes it?", None,
             IntakeAnswerKind.TEXT, None, None, False),
        ]
        seed_question_set(fresh_session, IntakeQuestionSet.ASSET, minimal, {})
        asset_questions = fresh_session.scalars(
            select(IntakeQuestion).where(IntakeQuestion.question_set == IntakeQuestionSet.ASSET)
        ).all()
        assert [q.code for q in asset_questions] == ["AS-TEST1"]

        seed_question_set(fresh_session, IntakeQuestionSet.ASSET, minimal, {})
        asset_questions_again = fresh_session.scalars(
            select(IntakeQuestion).where(IntakeQuestion.question_set == IntakeQuestionSet.ASSET)
        ).all()
        assert [q.code for q in asset_questions_again] == ["AS-TEST1"]
