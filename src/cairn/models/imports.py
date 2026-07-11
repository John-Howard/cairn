from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from cairn.models.base import AuditedBase
from cairn.models.enums import ImportBatchStatus


class ImportBatch(AuditedBase):
    __tablename__ = "import_batch"

    filename: Mapped[str]
    status: Mapped[ImportBatchStatus] = mapped_column(default=ImportBatchStatus.PENDING)
    rows: Mapped[list] = mapped_column(JSON)
