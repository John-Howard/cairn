from datetime import date

from sqlalchemy import select

from cairn.models import (
    ActivityDataCategory,
    AssetStatus,
    EntryStatus,
    InformationAsset,
    PersonalDataCategory,
    ProcessingActivity,
)
from cairn.rules import evaluate, evaluate_asset
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


def test_rule23_not_applicable_without_data_categories(session, actor, frs_profile):
    activity = make_activity(session, actor)
    assert _rule_finding(evaluate(activity, frs_profile), "23") is None


def test_rule23_fires_without_linked_asset(session, actor, frs_profile):
    activity = make_activity(session, actor)
    category = session.scalars(select(PersonalDataCategory)).first()
    session.add(ActivityDataCategory(activity_id=activity.id, category_id=category.id))
    session.flush()
    finding = _rule_finding(evaluate(activity, frs_profile), "23")
    assert finding is not None
    assert finding.severity.value == "warn"


def test_rule23_clears_with_linked_asset(session, actor, frs_profile):
    activity = make_activity(session, actor)
    category = session.scalars(select(PersonalDataCategory)).first()
    session.add(ActivityDataCategory(activity_id=activity.id, category_id=category.id))
    asset = InformationAsset(label="Case Management System")
    session.add(asset)
    session.flush()
    activity.assets.append(asset)
    session.flush()
    assert _rule_finding(evaluate(activity, frs_profile), "23") is None


def test_rule22_not_applicable_when_proposed(session):
    asset = InformationAsset(
        label="Proposed Asset", contains_personal_data=True, entry_status=EntryStatus.PROPOSED
    )
    session.add(asset)
    session.flush()
    assert evaluate_asset(asset, 0) is None


def test_rule22_not_applicable_when_not_personal_data(session):
    asset = InformationAsset(label="Non Personal Asset", contains_personal_data=False)
    session.add(asset)
    session.flush()
    assert evaluate_asset(asset, 0) is None


def test_rule22_not_applicable_when_disposed(session):
    asset = InformationAsset(
        label="Disposed Asset", contains_personal_data=True, status=AssetStatus.DISPOSED
    )
    session.add(asset)
    session.flush()
    assert evaluate_asset(asset, 0) is None


def test_rule22_fires_when_approved_personal_data_no_links(session):
    asset = InformationAsset(label="Orphan Asset", contains_personal_data=True)
    session.add(asset)
    session.flush()
    finding = evaluate_asset(asset, 0)
    assert finding is not None
    assert finding.rule_id == "22"
    assert finding.severity.value == "warn"


def test_rule22_clears_when_linked(session):
    asset = InformationAsset(label="Linked Asset", contains_personal_data=True)
    session.add(asset)
    session.flush()
    assert evaluate_asset(asset, 1) is None
