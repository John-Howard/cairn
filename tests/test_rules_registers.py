from datetime import date

from cairn.models import (
    DPIA,
    ActivityFeeds,
    ActivityType,
    AdequacyStatus,
    ADMUseMode,
    DecisionSupportADM,
    ExternalDataSource,
    ExternalDataUseMode,
    LifecycleStage,
    LineageGranularity,
    ProcessingActivity,
    Recipient,
    RecipientType,
    ScreeningOutcome,
    SourceSpecialCategory,
    ThirdCountry,
    Transfer,
)
from cairn.rules import Severity, evaluate
from conftest import business_function, transfer_mechanism


def make_activity(session, actor, **overrides):
    defaults = dict(
        name="Test Activity",
        business_function_id=business_function(session, "Prevention & Community Safety").id,
        purpose="Test purpose.",
        personal_data_source=["from_data_subject"],
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    defaults.update(overrides)
    activity = ProcessingActivity(**defaults)
    session.add(activity)
    session.flush()
    return activity


def make_dpia(session, activity, **overrides):
    defaults = dict(activity_id=activity.id, screening_outcome=ScreeningOutcome.NOT_REQUIRED)
    defaults.update(overrides)
    dpia = DPIA(**defaults)
    session.add(dpia)
    session.flush()
    return dpia


def _rule_finding(findings, rule_id):
    return next((f for f in findings if f.rule_id == rule_id), None)


def test_rule7_not_applicable_without_flags(session, actor, frs_profile):
    activity = make_activity(session, actor)
    assert _rule_finding(evaluate(activity, frs_profile), "7") is None


def test_rule7_fires_for_vulnerable_flag_without_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor, vulnerable_or_safeguarding_flag=True)
    finding = _rule_finding(evaluate(activity, frs_profile), "7")
    assert finding is not None
    assert finding.severity == Severity.BLOCK
    assert "DPIA" in finding.message


def test_rule7_fires_for_children_flag_without_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor, children_flag=True)
    assert _rule_finding(evaluate(activity, frs_profile), "7") is not None


def test_rule7_clears_with_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor, vulnerable_or_safeguarding_flag=True)
    make_dpia(session, activity)
    assert _rule_finding(evaluate(activity, frs_profile), "7") is None


def test_rule9_silent_when_module_off(session, actor, private_profile):
    activity = make_activity(session, actor)
    source = ExternalDataSource(
        name="CACI Acorn", special_category=SourceSpecialCategory.INFERRED
    )
    activity.data_sources.append(source)
    session.flush()
    assert _rule_finding(evaluate(activity, private_profile), "9") is None


def test_rule9_not_applicable_for_none_special_category(session, actor, frs_profile):
    activity = make_activity(session, actor)
    source = ExternalDataSource(name="Plain source")
    activity.data_sources.append(source)
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "9") is None


def test_rule9_fires_for_inferred_source_without_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor)
    source = ExternalDataSource(
        name="CACI Acorn", special_category=SourceSpecialCategory.INFERRED
    )
    activity.data_sources.append(source)
    session.flush()
    finding = _rule_finding(evaluate(activity, frs_profile), "9")
    assert finding is not None
    assert "DPIA" in finding.message


def test_rule9_fires_for_direct_source_without_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor)
    source = ExternalDataSource(
        name="Adult Care referrals", special_category=SourceSpecialCategory.DIRECT
    )
    activity.data_sources.append(source)
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "9") is not None


def test_rule9_clears_with_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor)
    source = ExternalDataSource(
        name="CACI Acorn", special_category=SourceSpecialCategory.INFERRED
    )
    activity.data_sources.append(source)
    make_dpia(session, activity)
    assert _rule_finding(evaluate(activity, frs_profile), "9") is None


def test_rule10_not_applicable_for_operational_activity(session, actor, frs_profile):
    activity = make_activity(session, actor, activity_type=ActivityType.OPERATIONAL)
    assert _rule_finding(evaluate(activity, frs_profile), "10") is None


def test_rule10_fires_without_feeds(session, actor, frs_profile):
    activity = make_activity(session, actor, activity_type=ActivityType.ANALYTICS_MODELLING)
    finding = _rule_finding(evaluate(activity, frs_profile), "10")
    assert finding is not None
    assert "feed at least one operational activity" in finding.message


def test_rule10_fires_without_dpia_when_feeds_present(session, actor, frs_profile):
    activity = make_activity(session, actor, activity_type=ActivityType.ANALYTICS_MODELLING)
    consumer = make_activity(session, actor, name="Consumer Activity")
    session.add(ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=consumer.id))
    session.flush()
    finding = _rule_finding(evaluate(activity, frs_profile), "10")
    assert finding is not None
    assert "DPIA" in finding.message


def test_rule10_fires_for_lineage_when_automated_and_significant_effects(
    session, actor, frs_profile
):
    activity = make_activity(
        session,
        actor,
        activity_type=ActivityType.ANALYTICS_MODELLING,
        external_data_use_mode=ExternalDataUseMode.AUTOMATED,
        lineage_granularity=LineageGranularity.ACTIVITY,
    )
    consumer = make_activity(session, actor, name="Consumer Activity")
    session.add(ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=consumer.id))
    make_dpia(session, activity)
    session.add(
        DecisionSupportADM(
            activity_id=activity.id,
            use_mode=ADMUseMode.AUTOMATED,
            significant_effects=True,
        )
    )
    session.flush()
    finding = _rule_finding(evaluate(activity, frs_profile), "10")
    assert finding is not None
    assert "record-level lineage" in finding.message


def test_rule10_clears_when_all_satisfied(session, actor, frs_profile):
    activity = make_activity(
        session,
        actor,
        activity_type=ActivityType.ANALYTICS_MODELLING,
        external_data_use_mode=ExternalDataUseMode.AUTOMATED,
        lineage_granularity=LineageGranularity.RECORD,
    )
    consumer = make_activity(session, actor, name="Consumer Activity")
    session.add(ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=consumer.id))
    make_dpia(session, activity)
    session.add(
        DecisionSupportADM(
            activity_id=activity.id,
            use_mode=ADMUseMode.AUTOMATED,
            significant_effects=True,
        )
    )
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "10") is None


def _make_transfer(session, activity, *, mechanism_code, data_protection_test=None):
    recipient = Recipient(label="Overseas Processor", type=RecipientType.PROCESSOR)
    country = ThirdCountry(label="Testland", adequacy_status=AdequacyStatus.NOT_ADEQUATE)
    session.add_all([recipient, country])
    session.flush()
    transfer = Transfer(
        activity_id=activity.id,
        recipient_id=recipient.id,
        third_country_id=country.id,
        mechanism_id=transfer_mechanism(session, mechanism_code).id,
        data_protection_test=data_protection_test,
    )
    session.add(transfer)
    session.flush()
    return transfer


def test_rule11_not_applicable_without_transfers(session, actor, frs_profile):
    activity = make_activity(session, actor)
    assert _rule_finding(evaluate(activity, frs_profile), "11") is None


def test_rule11_adequacy_exempt(session, actor, frs_profile):
    activity = make_activity(session, actor)
    _make_transfer(session, activity, mechanism_code="adequacy")
    assert _rule_finding(evaluate(activity, frs_profile), "11") is None


def test_rule11_art49_exception_exempt(session, actor, frs_profile):
    activity = make_activity(session, actor)
    _make_transfer(session, activity, mechanism_code="art49_exception")
    assert _rule_finding(evaluate(activity, frs_profile), "11") is None


def test_rule11_idta_fires_without_test(session, actor, frs_profile):
    activity = make_activity(session, actor)
    _make_transfer(session, activity, mechanism_code="idta")
    finding = _rule_finding(evaluate(activity, frs_profile), "11")
    assert finding is not None
    assert "s85" in finding.message


def test_rule11_idta_clears_with_test(session, actor, frs_profile):
    activity = make_activity(session, actor)
    _make_transfer(
        session,
        activity,
        mechanism_code="idta",
        data_protection_test="Assessed as not materially lower.",
    )
    assert _rule_finding(evaluate(activity, frs_profile), "11") is None


def test_rule14_not_applicable_when_live(session, actor, frs_profile):
    activity = make_activity(session, actor, lifecycle_stage=LifecycleStage.LIVE)
    assert _rule_finding(evaluate(activity, frs_profile), "14") is None


def test_rule14_fires_without_trial_end_or_dpia(session, actor, frs_profile):
    activity = make_activity(session, actor, lifecycle_stage=LifecycleStage.TRIAL)
    finding = _rule_finding(evaluate(activity, frs_profile), "14")
    assert finding is not None
    assert "trial end date" in finding.message


def test_rule14_fires_with_trial_end_but_no_dpia(session, actor, frs_profile):
    activity = make_activity(
        session, actor, lifecycle_stage=LifecycleStage.TRIAL, trial_end=date(2027, 1, 1)
    )
    assert _rule_finding(evaluate(activity, frs_profile), "14") is not None


def test_rule14_fires_with_dpia_but_no_trial_end(session, actor, frs_profile):
    activity = make_activity(session, actor, lifecycle_stage=LifecycleStage.TRIAL)
    make_dpia(session, activity)
    assert _rule_finding(evaluate(activity, frs_profile), "14") is not None


def test_rule14_clears_with_both(session, actor, frs_profile):
    activity = make_activity(
        session, actor, lifecycle_stage=LifecycleStage.TRIAL, trial_end=date(2027, 1, 1)
    )
    make_dpia(session, activity)
    assert _rule_finding(evaluate(activity, frs_profile), "14") is None
