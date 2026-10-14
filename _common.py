import enum
from datetime import datetime, timezone

from sqlalchemy import Enum


def utcnow() -> datetime:
    """Naive UTC timestamp (MySQL DATETIME has no timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enum_column(enum_cls: type[enum.Enum], length: int = 20) -> Enum:
    """Persist enum *values* as short strings (no native ENUM => painless migrations)."""
    return Enum(enum_cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])
