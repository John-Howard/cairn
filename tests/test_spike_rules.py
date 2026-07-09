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
from conftest import art6, business_function


def make_statutory_activity(session, actor, art6_code):
    activity = ProcessingActivity(
        name="Community Safety Programme",
        business_function_id=business_function(session, "Prevention & Community Safety").id,
        purpose="Deliver community fire-safety engagement.",
        personal_data_source=["from_data_subject"],
        is_statutory_task=True,
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    activity.basis_records.append(
        LawfulBasisRecord(regime_scope=RegimeScope.PART2, art6_basis=art6(session, art6_code))
    )
    session.add(activity)
    session.flush()
    return activity


def test_public_authority_guard_fires_only_for_guarded_public_profile(
    session, frs_profile, private_profile, actor
):
    activity = make_statutory_activity(session, actor, art6_code="f")

    public_findings = evaluate(activity, frs_profile)
    assert [f.rule_id for f in public_findings] == ["4"]
    assert public_findings[0].severity == Severity.WARN

    assert evaluate(activity, private_profile) == []


def test_public_authority_guard_silent_on_public_task_basis(session, frs_profile, actor):
    activity = make_statutory_activity(session, actor, art6_code="e")
    assert evaluate(activity, frs_profile) == []


def test_external_data_rule_gated_by_module(session, frs_profile, private_profile, actor):
    activity = make_statutory_activity(session, actor, art6_code="e")
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
