from __future__ import annotations

import datetime as dt

from flask_login import UserMixin
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager
from ._common import utcnow


class User(UserMixin, db.Model):
    """An account. Every other table is scoped by user_id => strict multi-user isolation."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    rules = relationship("CategoryRule", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    budgets = relationship("Budget", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    import_batches = relationship("ImportBatch", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return value.strip().lower()

    def set_password(self, password: str) -> None:
        """Salted scrypt hash (werkzeug default); the plaintext is never stored."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.email}>"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))
