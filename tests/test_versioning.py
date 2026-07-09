import pytest
from sqlalchemy import select

from cairn.models import BusinessFunction, RecordVersion


def first_function(session):
    return session.scalars(select(BusinessFunction)).first()


def versions_for(session, entity):
    return session.scalars(
        select(RecordVersion).where(
            RecordVersion.entity_type == "business_function",
            RecordVersion.entity_id == entity.id,
        )
    ).all()


def test_update_with_actor_auto_versions(session, actor):
    function = first_function(session)
    old_label = function.label
    function.change_note = "Rename function"
    function.label = "Renamed Function"
    session.flush()

    versions = versions_for(session, function)
    assert len(versions) == 1
    prior = versions[0]
    assert prior.entity_version == 1
    assert prior.snapshot["label"] == old_label
    assert prior.changed_by == actor.id
    assert prior.version_change_note == "Rename function"
    assert function.version == 2
    assert function.updated_by == actor.id


def test_update_without_actor_raises(session):
    function = first_function(session)
    function.label = "Renamed Without Actor"
    with pytest.raises(RuntimeError):
        session.flush()


def test_insert_does_not_version(session):
    function = BusinessFunction(label="New Function")
    session.add(function)
    session.flush()

    assert function.version == 1
    assert versions_for(session, function) == []
