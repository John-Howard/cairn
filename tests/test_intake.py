from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    AuditEvent,
    ControllerOrProcessor,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataUseMode,
    IntakeGap,
    IntakeQuestion,
    IntakeStatus,
    IntakeSubmission,
    LifecycleStage,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecordStatus,
    Regime,
    SystemAsset,
)
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
        from conftest import business_function

        function_id = business_function(db, function).id
    response = client.post(
        "/intake",
        data={
            "csrf_token": token,
            "activity_name": name,
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
        assert {s.label for s in activity.systems} == {"HFSV mobile app"}

        proposed_system = db.scalars(
            select(SystemAsset).where(SystemAsset.label == "HFSV mobile app")
        ).one()
        assert proposed_system.entry_status == EntryStatus.PROPOSED

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
        from conftest import business_function

        protection_id = business_function(db, PROTECTION).id
    response = client.post(
        "/intake",
        data={
            "csrf_token": token,
            "activity_name": "Sneaky cross-function intake",
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
