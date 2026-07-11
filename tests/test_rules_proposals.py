from datetime import date

from cairn.models import (
    ActivityRetention,
    ActivitySecurity,
    EntryStatus,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RetentionRule,
    SecurityMeasure,
    SecurityMeasureCategory,
)
from cairn.rules import Severity, evaluate
from conftest import business_function


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


def _rule_finding(findings, rule_id):
    return next((f for f in findings if f.rule_id == rule_id), None)


def test_rule18_silent_with_no_links(session, actor, frs_profile):
    activity = make_activity(session, actor)
    assert _rule_finding(evaluate(activity, frs_profile), "18") is None


def test_rule18_fires_for_proposed_recipient(session, actor, frs_profile):
    activity = make_activity(session, actor)
    recipient = Recipient(
        label="Proposed Recipient",
        type=RecipientType.PUBLIC_BODY,
        entry_status=EntryStatus.PROPOSED,
    )
    session.add(recipient)
    activity.recipients.append(recipient)
    session.flush()

    finding = _rule_finding(evaluate(activity, frs_profile), "18")
    assert finding is not None
    assert finding.severity == Severity.BLOCK
    assert "Proposed Recipient" in finding.message


def test_rule18_fires_for_rejected_recipient(session, actor, frs_profile):
    activity = make_activity(session, actor)
    recipient = Recipient(
        label="Rejected Recipient",
        type=RecipientType.PUBLIC_BODY,
        entry_status=EntryStatus.REJECTED,
    )
    session.add(recipient)
    activity.recipients.append(recipient)
    session.flush()

    assert _rule_finding(evaluate(activity, frs_profile), "18") is not None


def test_rule18_clears_after_approval(session, actor, frs_profile):
    activity = make_activity(session, actor)
    recipient = Recipient(
        label="Proposed Recipient",
        type=RecipientType.PUBLIC_BODY,
        entry_status=EntryStatus.PROPOSED,
    )
    session.add(recipient)
    activity.recipients.append(recipient)
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "18") is not None

    recipient.entry_status = EntryStatus.APPROVED
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "18") is None


def test_rule18_fires_for_proposed_retention_link(session, actor, frs_profile):
    activity = make_activity(session, actor)
    rule = RetentionRule(
        label="Proposed Rule",
        period="6 years",
        trigger="End of case",
        entry_status=EntryStatus.PROPOSED,
    )
    session.add(rule)
    session.flush()
    session.add(ActivityRetention(activity_id=activity.id, retention_rule_id=rule.id))
    session.flush()

    finding = _rule_finding(evaluate(activity, frs_profile), "18")
    assert finding is not None
    assert "Proposed Rule" in finding.message


def test_rule18_fires_for_proposed_security_link(session, actor, frs_profile):
    activity = make_activity(session, actor)
    measure = SecurityMeasure(
        label="Proposed Measure",
        category=SecurityMeasureCategory.TECHNICAL,
        entry_status=EntryStatus.PROPOSED,
    )
    session.add(measure)
    session.flush()
    session.add(ActivitySecurity(activity_id=activity.id, security_measure_id=measure.id))
    session.flush()

    finding = _rule_finding(evaluate(activity, frs_profile), "18")
    assert finding is not None
    assert "Proposed Measure" in finding.message
