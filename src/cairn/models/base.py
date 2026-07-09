import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AuditedBase(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("user.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("user.id"))
    version: Mapped[int] = mapped_column(default=1)
    change_note: Mapped[str | None]
