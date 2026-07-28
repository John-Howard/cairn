from datetime import date

from cairn.inheritance import sync_inherited_security
from cairn.models import (
    ActivitySecurity,
    InformationAsset,
    ProcessingActivity,
    SecurityMeasure,
    SecurityMeasureCategory,
)
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


def make_system(session, label, *measures):
    system = InformationAsset(label=label)
    system.security_measures.extend(measures)
    session.add(system)
    session.flush()
    return system


def make_measure(session, label):
    measure = SecurityMeasure(label=label, category=SecurityMeasureCategory.TECHNICAL)
    session.add(measure)
    session.flush()
    return measure


def _links_by_measure(activity):
    return {link.security_measure_id: link for link in activity.security_links}


def test_sync_creates_inherited_rows_for_union_of_linked_systems(session, actor):
    encryption = make_measure(session, "encryption at rest")
    mfa = make_measure(session, "multi-factor authentication")
    logging_measure = make_measure(session, "audit logging")
    system_a = make_system(session, "System A", encryption, mfa)
    system_b = make_system(session, "System B", mfa, logging_measure)

    activity = make_activity(session, actor)
    activity.assets.extend([system_a, system_b])
    session.flush()

    sync_inherited_security(session, activity)
    session.flush()
    session.refresh(activity)

    links = _links_by_measure(activity)
    assert set(links) == {encryption.id, mfa.id, logging_measure.id}
    assert all(link.inherited_from_system for link in links.values())
    assert len(activity.security_links) == 3


def test_sync_is_idempotent(session, actor):
    encryption = make_measure(session, "encryption at rest")
    system_a = make_system(session, "System A", encryption)

    activity = make_activity(session, actor)
    activity.assets.append(system_a)
    session.flush()

    sync_inherited_security(session, activity)
    sync_inherited_security(session, activity)
    session.refresh(activity)

    assert len(activity.security_links) == 1


def test_unlinking_system_removes_exclusive_inherited_rows_but_keeps_shared(session, actor):
    encryption = make_measure(session, "encryption at rest")
    mfa = make_measure(session, "multi-factor authentication")
    system_a = make_system(session, "System A", encryption, mfa)
    system_b = make_system(session, "System B", mfa)

    activity = make_activity(session, actor)
    activity.assets.extend([system_a, system_b])
    session.flush()
    sync_inherited_security(session, activity)
    session.refresh(activity)
    assert set(_links_by_measure(activity)) == {encryption.id, mfa.id}

    activity.assets.remove(system_a)
    session.flush()
    sync_inherited_security(session, activity)
    session.refresh(activity)

    links = _links_by_measure(activity)
    assert set(links) == {mfa.id}


def test_manual_row_is_never_touched(session, actor):
    encryption = make_measure(session, "encryption at rest")
    system_a = make_system(session, "System A", encryption)

    activity = make_activity(session, actor)
    manual = ActivitySecurity(
        activity_id=activity.id,
        security_measure_id=encryption.id,
        inherited_from_system=False,
    )
    session.add(manual)
    session.flush()

    sync_inherited_security(session, activity)
    session.refresh(activity)
    links = _links_by_measure(activity)
    assert len(links) == 1
    assert links[encryption.id].inherited_from_system is False

    activity.assets.append(system_a)
    session.flush()
    sync_inherited_security(session, activity)
    session.refresh(activity)

    links = _links_by_measure(activity)
    assert len(links) == 1
    assert links[encryption.id].inherited_from_system is False

    activity.assets.remove(system_a)
    session.flush()
    sync_inherited_security(session, activity)
    session.refresh(activity)

    links = _links_by_measure(activity)
    assert len(links) == 1
    assert links[encryption.id].inherited_from_system is False


def test_manual_row_for_non_inherited_measure_untouched_when_system_unlinked(session, actor):
    encryption = make_measure(session, "encryption at rest")
    other = make_measure(session, "pseudonymisation")
    system_a = make_system(session, "System A", encryption)

    activity = make_activity(session, actor)
    activity.assets.append(system_a)
    manual = ActivitySecurity(
        activity_id=activity.id, security_measure_id=other.id, inherited_from_system=False
    )
    session.add(manual)
    session.flush()

    sync_inherited_security(session, activity)
    session.refresh(activity)
    links = _links_by_measure(activity)
    assert set(links) == {encryption.id, other.id}

    activity.assets.remove(system_a)
    session.flush()
    sync_inherited_security(session, activity)
    session.refresh(activity)

    links = _links_by_measure(activity)
    assert set(links) == {other.id}
    assert links[other.id].inherited_from_system is False
