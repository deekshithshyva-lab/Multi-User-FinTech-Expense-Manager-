from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from ._common import utcnow


class ImportBatch(db.Model):
    """Audit record for one CSV upload: powers the upload history and 'undo import'."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    date_format: Mapped[str | None] = mapped_column(String(30))
    column_mapping: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    user = relationship("User", back_populates="import_batches")
    transactions = relationship("Transaction", back_populates="import_batch", passive_deletes=True)
