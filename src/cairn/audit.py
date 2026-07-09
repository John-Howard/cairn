from datetime import date, datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cairn.models import AuditedBase, AuditEvent, User


def _serialize(data: dict) -> dict:
    return {
        key: value.isoformat() if isinstance(value, datetime | date) else value
        for key, value in data.items()
    }


def snapshot(entity: AuditedBase) -> dict:
    data = {attr.key: getattr(entity, attr.key) for attr in inspect(entity).mapper.column_attrs}
    return _serialize(data)


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
