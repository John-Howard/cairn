from datetime import date

from cairn.models import (
    ExternalDataSource,
    ExternalDataUseMode,
    LawfulBasisRecord,
    PersonalDataCategory,
    ProcessingActivity,
    RegimeScope,
    SourceSpecialCategory,
)
from cairn.rules import Severity, evaluate


def make_statutory_activity(session, actor, art6_basis):
    activity = ProcessingActivity(
        name="Community Safety Programme",
        purpose="Deliver community fire-safety engagement.",
        is_statutory_task=True,
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    activity.basis_records.append(
        LawfulBasisRecord(regime_scope=RegimeScope.PART2, art6_basis=art6_basis)
    )
    session.add(activity)
    session.flush()
    return activity


def test_public_authority_guard_fires_only_for_guarded_public_profile(
    session, frs_profile, private_profile, actor
):
    activity = make_statutory_activity(session, actor, art6_basis="f")

    public_findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in public_findings] == ["4"]
    assert public_findings[0].severity == Severity.WARN

    assert evaluate(activity, private_profile) == []


def test_public_authority_guard_silent_on_public_task_basis(session, frs_profile, actor):
    activity = make_statutory_activity(session, actor, art6_basis="e")
    assert evaluate(activity, frs_profile) == []


def test_external_data_rule_gated_by_module(session, frs_profile, private_profile, actor):
    activity = make_statutory_activity(session, actor, art6_basis="e")
    activity.external_data_use_mode = ExternalDataUseMode.MANUAL
    session.flush()

    findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in findings] == ["8"]
    assert findings[0].severity == Severity.BLOCK

    assert evaluate(activity, private_profile) == []

    activity.data_sources.append(
        ExternalDataSource(name="CACI Acorn", special_category=SourceSpecialCategory.INFERRED)
    )
    session.flush()
    assert evaluate(activity, frs_profile) == []


def test_special_category_rule_follows_active_regime(session, frs_profile, enforcement_activity):
    health = PersonalDataCategory(label="health data", is_special_category=True)
    enforcement_activity.data_categories.append(health)
    session.flush()

    assert evaluate(enforcement_activity, frs_profile) == []

    basis = enforcement_activity.basis_records[0]
    basis.schedule8_condition = None
    session.flush()
    findings = evaluate(enforcement_activity, frs_profile)
    assert [f.rule_id for f in findings] == ["1"]
    assert "Schedule 8" in findings[0].message
