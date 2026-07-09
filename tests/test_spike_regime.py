import pytest
from sqlalchemy import select

from cairn.audit import snapshot
from cairn.export import export_views
from cairn.models import (
    ActivityDomain,
    APDScope,
    AuditEvent,
    LawfulBasisRecord,
    RecordVersion,
    Regime,
    RegimeScope,
    RegimeSource,
)
from cairn.regime import (
    active_basis,
    inactive_basis,
    override_activity_regime,
    resolve_regime,
    set_regime_policy,
)
from cairn.rules import evaluate
from conftest import art6, make_apd, schedule1


def flip_policy(session, regime, actor, reason):
    return set_regime_policy(
        session,
        domain=ActivityDomain.FIRE_SAFETY_ENFORCEMENT,
        regime=regime,
        reason=reason,
        actor=actor,
    )


def activity_regime_changes(session, activity):
    return session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == "processing_activity",
            AuditEvent.entity_id == activity.id,
            AuditEvent.event == "regime_change",
        )
    ).all()


def test_le_baseline_validates_clean_and_exports_s61(session, frs_profile, enforcement_activity):
    assert resolve_regime(session, enforcement_activity) == Regime.LAW_ENFORCEMENT
    assert active_basis(enforcement_activity).regime_scope == RegimeScope.PART3

    findings = evaluate(enforcement_activity, frs_profile)
    assert findings == []

    assert export_views(enforcement_activity, frs_profile) == {"s61"}


def test_policy_flip_to_part2_switches_set_and_retains_part3(
    session, frs_profile, enforcement_activity, actor
):
    flip_policy(session, Regime.GENERAL, actor, "DPO position: treat as Part 2 with Art 10 data")

    assert enforcement_activity.regime == Regime.GENERAL
    assert enforcement_activity.regime_source == RegimeSource.POLICY

    rule_ids = {f.rule_id for f in evaluate(enforcement_activity, frs_profile)}
    assert "12" in rule_ids
    assert "3" in rule_ids

    retained = inactive_basis(enforcement_activity)
    assert retained is not None
    assert retained.regime_scope == RegimeScope.PART3
    assert retained.s35_basis.code == "s35_task"

    events = activity_regime_changes(session, enforcement_activity)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == actor.id
    assert event.reason == "DPO position: treat as Part 2 with Art 10 data"
    assert event.old_value == {"regime": "law_enforcement"}
    assert event.new_value == {"regime": "general"}

    assert export_views(enforcement_activity, frs_profile) == {"art30_1"}

    apd = make_apd(
        session,
        title="APD — Enforcement (Schedule 1)",
        scope=APDScope.SCHEDULE1,
        document_ref="apd_enforcement",
    )
    enforcement_activity.basis_records.append(
        LawfulBasisRecord(
            regime_scope=RegimeScope.PART2,
            art6_basis=art6(session, "e"),
            art10_basis="schedule1_para_10",
            schedule1_condition=schedule1(session, 10),
            apd=apd,
        )
    )
    session.flush()
    assert evaluate(enforcement_activity, frs_profile) == []


def test_round_trip_flip_preserves_part3_mapping(session, frs_profile, enforcement_activity, actor):
    before = snapshot(active_basis(enforcement_activity))

    flip_policy(session, Regime.GENERAL, actor, "Reclassify as Part 2")
    flip_policy(session, Regime.LAW_ENFORCEMENT, actor, "Revert to Part 3 on legal advice")

    assert enforcement_activity.regime == Regime.LAW_ENFORCEMENT
    after = snapshot(active_basis(enforcement_activity))
    assert {k: v for k, v in after.items() if k != "updated_at"} == {
        k: v for k, v in before.items() if k != "updated_at"
    }

    events = activity_regime_changes(session, enforcement_activity)
    assert len(events) == 2


def test_manual_override_requires_reason_and_pins_regime(
    session, frs_profile, enforcement_activity, actor
):
    with pytest.raises(ValueError):
        override_activity_regime(
            session, enforcement_activity, regime=Regime.GENERAL, reason="", actor=actor
        )

    override_activity_regime(
        session,
        enforcement_activity,
        regime=Regime.GENERAL,
        reason="This activity is advisory only — no prosecution function",
        actor=actor,
    )
    assert enforcement_activity.regime == Regime.GENERAL
    assert enforcement_activity.regime_source == RegimeSource.MANUAL_OVERRIDE

    flip_policy(session, Regime.LAW_ENFORCEMENT, actor, "Domain default stays Part 3")
    assert enforcement_activity.regime == Regime.GENERAL
    assert resolve_regime(session, enforcement_activity) == Regime.GENERAL


def test_version_history_captured_on_edit(session, frs_profile, enforcement_activity, actor):
    original_purpose = enforcement_activity.purpose
    enforcement_activity.change_note = "Broaden purpose"
    enforcement_activity.purpose = "Investigate, enforce and prosecute fire-safety breaches."
    session.flush()

    versions = session.scalars(
        select(RecordVersion).where(RecordVersion.entity_id == enforcement_activity.id)
    ).all()
    assert len(versions) == 1
    prior = versions[0]
    assert prior.entity_version == 1
    assert prior.snapshot["purpose"] == original_purpose
    assert prior.changed_by == actor.id
    assert prior.version_change_note == "Broaden purpose"
    assert enforcement_activity.version == 2
