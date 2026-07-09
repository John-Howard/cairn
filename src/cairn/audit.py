from datetime import date, datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cairn.models import AuditedBase, AuditEvent, RecordVersion, User


def snapshot(entity: AuditedBase) -> dict:
    data = {}
    for attr in inspect(entity).mapper.column_attrs:
        value = getattr(entity, attr.key)
        if isinstance(value, datetime | date):
            value = value.isoformat()
        data[attr.key] = value
    return data


def record_event(
    session: Session,
    *,
    entity: AuditedBase,
    event: str,
    actor: User,
    reason: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> AuditEvent:
    audit = AuditEvent(
        entity_type=entity.__tablename__,
        entity_id=entity.id,
        event=event,
        actor_id=actor.id,
        reason=reason,
        old_value=old_value,
        new_value=new_value,
    )
    session.add(audit)
    return audit


def capture_version(
    session: Session,
    entity: AuditedBase,
    *,
    changed_by: User,
    change_note: str | None = None,
) -> RecordVersion:
    prior = RecordVersion(
        entity_type=entity.__tablename__,
        entity_id=entity.id,
        entity_version=entity.version,
        snapshot=snapshot(entity),
        changed_by=changed_by.id,
        version_change_note=change_note,
    )
    session.add(prior)
    entity.version += 1
    entity.change_note = change_note
    return prior
