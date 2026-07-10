from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    ActivityDomain,
    AuditEvent,
    ProcessingActivity,
    Regime,
    RegimePolicy,
    RegimeSource,
)
from test_activities import _create_activity, _extract_csrf, _login, _user_id


def _policy_token(client) -> str:
    return _extract_csrf(client.get("/regime-policy").text)


def test_page_is_approver_only(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    assert activities_client.get("/regime-policy").status_code == 403

    _login(activities_client, activities_web_engine, "Vic Viewer")
    assert activities_client.get("/regime-policy").status_code == 403

    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/regime-policy")
    assert response.status_code == 200
    for label in (
        "Fire safety enforcement",
        "Fire investigation",
        "Firesetter intervention",
        "Other",
    ):
        assert label in response.text
    assert "Not set" in response.text


def test_set_policy_cascades_and_respects_manual_override(
    activities_client, activities_web_engine
):
    policy_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        name="Policy-sourced enforcement",
        activity_domain="fire_safety_enforcement",
    )
    override_activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        name="Manually-overridden enforcement",
        activity_domain="fire_safety_enforcement",
    )
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        overridden = db.get(ProcessingActivity, override_activity_id)
        overridden.regime_source = RegimeSource.MANUAL_OVERRIDE
        overridden.regime_override_reason = "Kept general deliberately"
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _policy_token(activities_client)
    response = activities_client.post(
        "/regime-policy/fire_safety_enforcement",
        data={
            "csrf_token": token,
            "assigned_regime": "law_enforcement",
            "rationale": "Fire-safety prosecution is competent-authority processing",
        },
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "moved=1" in location

    confirmation = activities_client.get(location)
    assert confirmation.status_code == 200
    assert "1 activity moved" in confirmation.text

    with Session(activities_web_engine) as db:
        policy = db.scalars(
            select(RegimePolicy).where(
                RegimePolicy.activity_domain == ActivityDomain.FIRE_SAFETY_ENFORCEMENT
            )
        ).one()
        assert policy.assigned_regime == Regime.LAW_ENFORCEMENT

        moved = db.get(ProcessingActivity, policy_activity_id)
        assert moved.regime == Regime.LAW_ENFORCEMENT
        assert moved.regime_source == RegimeSource.POLICY

        untouched = db.get(ProcessingActivity, override_activity_id)
        assert untouched.regime == Regime.GENERAL
        assert untouched.regime_source == RegimeSource.MANUAL_OVERRIDE

        policy_events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "regime_policy")
        ).all()
        assert len(policy_events) == 1
        assert policy_events[0].event == "policy_created"

        regime_changes = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "processing_activity",
                AuditEvent.event == "regime_change",
            )
        ).all()
        assert [e.entity_id for e in regime_changes] == [policy_activity_id]

    history = activities_client.get("/regime-policy")
    assert "policy_created" in history.text
    assert "regime_change" in history.text
    assert "Policy-sourced enforcement" in history.text


def test_missing_rationale_is_rejected(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _policy_token(activities_client)
    response = activities_client.post(
        "/regime-policy/fire_investigation",
        data={"csrf_token": token, "assigned_regime": "law_enforcement", "rationale": "  "},
    )
    assert response.status_code == 422
    assert "Enter a rationale" in response.text

    with Session(activities_web_engine) as db:
        assert db.scalars(select(RegimePolicy)).all() == []


def test_post_requires_approver_and_valid_domain(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.post(
        "/regime-policy/fire_investigation",
        data={"csrf_token": "x", "assigned_regime": "law_enforcement", "rationale": "reason"},
    )
    assert response.status_code == 403

    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _policy_token(activities_client)
    response = activities_client.post(
        "/regime-policy/not_a_domain",
        data={"csrf_token": token, "assigned_regime": "law_enforcement", "rationale": "reason"},
    )
    assert response.status_code == 404
