from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.models import (
    ACTIVE_SCOPE,
    ActivityDomain,
    LawfulBasisRecord,
    ProcessingActivity,
    Regime,
    RegimePolicy,
    RegimeSource,
    User,
)


def resolve_regime(session: Session, activity: ProcessingActivity) -> Regime:
    if activity.regime_source == RegimeSource.MANUAL_OVERRIDE:
        return activity.regime
    if activity.activity_domain is None:
        return Regime.GENERAL
    policy = session.scalar(
        select(RegimePolicy).where(RegimePolicy.activity_domain == activity.activity_domain)
    )
    return policy.assigned_regime if policy else Regime.GENERAL


def set_regime_policy(
    session: Session,
    *,
    domain: ActivityDomain,
    regime: Regime,
    reason: str,
    actor: User,
) -> RegimePolicy:
    if not reason:
        raise ValueError("A rationale is required to set a regime policy")

    policy = session.scalar(select(RegimePolicy).where(RegimePolicy.activity_domain == domain))
    if policy is None:
        policy = RegimePolicy(activity_domain=domain, assigned_regime=regime, rationale=reason)
        session.add(policy)
        session.flush()
        record_event(
            session,
            entity=policy,
            event="policy_created",
            actor=actor,
            reason=reason,
            new_value={"assigned_regime": regime},
        )
    elif policy.assigned_regime != regime:
        old = policy.assigned_regime
        policy.change_note = reason
        policy.assigned_regime = regime
        policy.rationale = reason
        record_event(
            session,
            entity=policy,
            event="policy_changed",
            actor=actor,
            reason=reason,
            old_value={"assigned_regime": old},
            new_value={"assigned_regime": regime},
        )

    affected = session.scalars(
        select(ProcessingActivity).where(
            ProcessingActivity.activity_domain == domain,
            ProcessingActivity.regime_source == RegimeSource.POLICY,
            ProcessingActivity.regime != regime,
        )
    ).all()
    for activity in affected:
        _change_regime(session, activity, regime=regime, reason=reason, actor=actor)
    return policy


def override_activity_regime(
    session: Session,
    activity: ProcessingActivity,
    *,
    regime: Regime,
    reason: str,
    actor: User,
) -> None:
    if not reason:
        raise ValueError("A documented reason is required to override an activity's regime")
    activity.regime_source = RegimeSource.MANUAL_OVERRIDE
    activity.regime_override_reason = reason
    if activity.regime != regime:
        _change_regime(session, activity, regime=regime, reason=reason, actor=actor)


def _change_regime(
    session: Session,
    activity: ProcessingActivity,
    *,
    regime: Regime,
    reason: str,
    actor: User,
) -> None:
    old = activity.regime
    activity.change_note = reason
    activity.regime = regime
    record_event(
        session,
        entity=activity,
        event="regime_change",
        actor=actor,
        reason=reason,
        old_value={"regime": old},
        new_value={"regime": regime},
    )


def active_basis(activity: ProcessingActivity) -> LawfulBasisRecord | None:
    scope = ACTIVE_SCOPE[activity.regime]
    return next((b for b in activity.basis_records if b.regime_scope == scope), None)


def inactive_basis(activity: ProcessingActivity) -> LawfulBasisRecord | None:
    scope = ACTIVE_SCOPE[activity.regime]
    return next((b for b in activity.basis_records if b.regime_scope != scope), None)
