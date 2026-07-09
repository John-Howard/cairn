from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from cairn.models.base import AuditedBase, utcnow


class AuditEvent(AuditedBase):
    __tablename__ = "audit_event"

    entity_type: Mapped[str]
    entity_id: Mapped[str]
    event: Mapped[str]
    actor_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    reason: Mapped[str | None] = mapped_column(Text)
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)


class RecordVersion(AuditedBase):
    __tablename__ = "record_version"

    entity_type: Mapped[str]
    entity_id: Mapped[str]
    entity_version: Mapped[int]
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(ForeignKey("user.id"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    version_change_note: Mapped[str | None]
