from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from cairn.audit import _serialize
from cairn.models import AuditedBase, RecordVersion


def _pre_change_snapshot(entity: AuditedBase) -> dict:
    state = inspect(entity)
    data = {}
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if history.deleted:
            value = history.deleted[0]
        elif history.unchanged:
            value = history.unchanged[0]
        else:
            value = getattr(entity, attr.key)
        data[attr.key] = value
    return _serialize(data)


def _before_flush(session: Session, flush_context: object, instances: object) -> None:
    actor_id = session.info.get("actor_id")
    for entity in session.new:
        if isinstance(entity, AuditedBase) and actor_id and entity.created_by is None:
            entity.created_by = actor_id
            entity.updated_by = actor_id
    for entity in list(session.dirty):
        if not isinstance(entity, AuditedBase):
            continue
        if not session.is_modified(entity, include_collections=False):
            continue
        if not actor_id:
            raise RuntimeError(
                "session.info['actor_id'] must be set before updating an audited record"
            )
        session.add(
            RecordVersion(
                entity_type=entity.__tablename__,
                entity_id=entity.id,
                entity_version=entity.version,
                snapshot=_pre_change_snapshot(entity),
                changed_by=actor_id,
                version_change_note=entity.change_note,
            )
        )
        entity.version += 1
        entity.updated_by = actor_id


event.listen(Session, "before_flush", _before_flush)
