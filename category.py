from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from ._common import enum_column, utcnow


class CategoryKind(str, enum.Enum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # card payments / own-account moves: excluded from spending analytics


class MatchType(str, enum.Enum):
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    EXACT = "exact"
    REGEX = "regex"


class Category(db.Model):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[CategoryKind] = mapped_column(enum_column(CategoryKind, 10), default=CategoryKind.EXPENSE)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")  # hex colour used by the charts

    user = relationship("User", back_populates="categories")
    rules = relationship("CategoryRule", back_populates="category", cascade="all, delete-orphan", passive_deletes=True)
    budgets = relationship("Budget", back_populates="category", cascade="all, delete-orphan", passive_deletes=True)
    # Deleting a category un-categorises its transactions (FK ON DELETE SET NULL), never deletes them.
    transactions = relationship("Transaction", back_populates="category", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class CategoryRule(db.Model):
    """User-editable auto-categorisation rule: description <match_type> pattern  =>  category.

    Rules run in ascending `priority` (lower first); put specific patterns ("uber eats", 50)
    ahead of generic ones ("uber", 100). The evaluation engine arrives in the next step.
    """

    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("user_id", "match_type", "pattern", name="uq_rules_user_type_pattern"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    pattern: Mapped[str] = mapped_column(String(120))
    match_type: Mapped[MatchType] = mapped_column(enum_column(MatchType, 12), default=MatchType.CONTAINS)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    user = relationship("User", back_populates="rules")
    category = relationship("Category", back_populates="rules")
