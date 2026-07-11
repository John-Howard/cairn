from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    DPIA,
    EntryStatus,
    LifecycleStage,
    OrganisationProfile,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    Regime,
    ScreeningOutcome,
)
from test_activities import _business_function_id, _extract_csrf, _login, _user_id


def _seed_dashboard_activities(engine) -> None:
    approver_id = _user_id(engine, "Ada Approver")
    prevention_id = _business_function_id(engine, "Prevention & Community Safety")
    protection_id = _business_function_id(
        engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    today = date.today()
    with Session(engine) as db:
        db.info["actor_id"] = approver_id
        trial_activity = ProcessingActivity(
            name="Trial Ending Activity",
            business_function_id=prevention_id,
            purpose="Purpose",
            personal_data_source=["from_data_subject"],
            owner_id=approver_id,
            next_review_at=today + timedelta(days=200),
            record_status=RecordStatus.DRAFT,
            lifecycle_stage=LifecycleStage.TRIAL,
            trial_start=today - timedelta(days=30),
            trial_end=today + timedelta(days=30),
        )
        db.add_all(
            [
                ProcessingActivity(
                    name="Overdue Review Activity",
                    business_function_id=prevention_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today - timedelta(days=10),
                    record_status=RecordStatus.ACTIVE,
                ),
                trial_activity,
                ProcessingActivity(
                    name="LE Register Activity",
                    business_function_id=protection_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today + timedelta(days=200),
                    record_status=RecordStatus.IN_REVIEW,
                    regime=Regime.LAW_ENFORCEMENT,
                ),
                ProcessingActivity(
                    name="Retired Old Activity",
                    business_function_id=protection_id,
                    purpose="Purpose",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=today - timedelta(days=400),
                    record_status=RecordStatus.RETIRED,
                ),
            ]
        )
        db.flush()
        db.add(
            DPIA(
                activity_id=trial_activity.id,
                screening_outcome=ScreeningOutcome.REQUIRED,
            )
        )
        db.commit()


def test_dashboard_counts_and_lists(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "4 processing activities recorded" in response.text

    assert "Overdue Review Activity" in response.text
    assert "Trial Ending Activity" in response.text
    assert "Ending soon" in response.text
    assert "Retired Old Activity" not in response.text

    assert "3 blocking" in response.text
    assert "0 warning" in response.text


def test_dashboard_empty_state(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "0 processing activities recorded" in response.text
    assert "No overdue reviews" in response.text
    assert "No trials ending within 60 days" in response.text
    assert ">—<" in response.text


def test_dashboard_review_compliance_and_blocked(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = _user_id(activities_web_engine, "Ada Approver")
        overdue = db.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.name == "Overdue Review Activity"
            )
        ).one()
        overdue.vulnerable_or_safeguarding_flag = True
        db.commit()

    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "67%" in response.text
    assert "4 blocking" in response.text
    assert "0 warning" in response.text
    marker = ">Activities blocked from approval</td>"
    start = response.text.index(marker) + len(marker)
    row_tail = response.text[start : start + 200]
    assert '--numeric">3</td>' in row_tail


def test_dashboard_review_compliance_full(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    function_id = _business_function_id(activities_web_engine, "Prevention & Community Safety")
    today = date.today()
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            ProcessingActivity(
                name="On Time Activity",
                business_function_id=function_id,
                purpose="Purpose",
                personal_data_source=["from_data_subject"],
                owner_id=approver_id,
                next_review_at=today + timedelta(days=200),
                record_status=RecordStatus.ACTIVE,
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "100%" in response.text


def test_dashboard_pending_proposals(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            Recipient(
                label="Proposed Recipient",
                type=RecipientType.OTHER,
                entry_status=EntryStatus.PROPOSED,
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Pending vocabulary proposals" in response.text
    assert '<a class="govuk-link" href="/vocabularies">1</a>' in response.text


def test_dashboard_export_coverage(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "Art 30(1)" in response.text
    assert "DPA 2018 s61" in response.text
    assert "Combined internal register" in response.text
    assert '/register/export/art30_1">Download CSV</a>' in response.text
    assert '/register/export/combined">Download CSV</a>' in response.text


def test_dashboard_no_commencement_watch_card_without_data(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "DUAA commencement" not in response.text


def test_dashboard_commencement_watch_card(activities_client, activities_web_engine):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        profile = db.scalars(select(OrganisationProfile)).one()
        profile.commencement_watch = {
            "duaa_principal": "2026-02-05",
            "s164a_complaints": "2026-06-19",
        }
        db.commit()

    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/")
    assert response.status_code == 200
    assert "DUAA commencement" in response.text
    assert "in force since 2026-02-05" in response.text
    assert "in force since 2026-06-19" in response.text


def test_register_lists_all_activities_for_viewer(activities_client, activities_web_engine):
    _seed_dashboard_activities(activities_web_engine)
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register")
    assert response.status_code == 200
    for name in (
        "Overdue Review Activity",
        "Trial Ending Activity",
        "LE Register Activity",
        "Retired Old Activity",
    ):
        assert name in response.text
    assert "Ada Approver" in response.text
    assert "s61" in response.text
    assert "art30_1" in response.text


def test_register_requires_login(activities_client):
    response = activities_client.get("/register")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_mark_reviewed_removes_activity_from_overdue_dashboard(
    activities_client, activities_web_engine
):
    _seed_dashboard_activities(activities_web_engine)
    with Session(activities_web_engine) as db:
        activity_id = db.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.name == "Overdue Review Activity"
            )
        ).one().id

    _login(activities_client, activities_web_engine, "Ada Approver")
    before = activities_client.get("/")
    assert "Overdue Review Activity" in before.text

    detail_page = activities_client.get(f"/activities/{activity_id}")
    token = _extract_csrf(detail_page.text)
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": future},
    )
    assert response.status_code == 302

    after = activities_client.get("/")
    assert "Overdue Review Activity" not in after.text
