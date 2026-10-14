from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from ._common import enum_column, utcnow


class CategorySource(str, enum.Enum):
    RULE = "rule"      # assigned by the rules engine (safe to recompute)
    MANUAL = "manual"  # chosen by the user (never overwritten by rules)


class Transaction(db.Model):
    """A single bank transaction.

    `amount` is SIGNED: negative = money out (expense), positive = money in (income).
    `fingerprint` makes imports idempotent: re-uploading the same statement is a no-op
    because (user_id, fingerprint) is unique.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_transactions_user_fingerprint"),
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_category", "user_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))

    date: Mapped[dt.date]
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    category_source: Mapped[CategorySource | None] = mapped_column(enum_column(CategorySource, 10), default=None)
    fingerprint: Mapped[str] = mapped_column(String(64))  # sha256 hex
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    user = relationship("User", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    import_batch = relationship("ImportBatch", back_populates="transactions")

    @property
    def is_expense(self) -> bool:
        return self.amount < 0

    def __repr__(self) -> str:
        return f"<Transaction {self.date} {self.amount} {self.description[:20]!r}>"
