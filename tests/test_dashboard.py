from datetime import date, timedelta

from sqlalchemy.orm import Session

from cairn.models import (
    DPIA,
    LifecycleStage,
    ProcessingActivity,
    RecordStatus,
    Regime,
    ScreeningOutcome,
)
from test_activities import _business_function_id, _login, _user_id


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
