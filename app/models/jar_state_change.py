"""Audit trail of a jar moving between counter, fridge and dormancy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import JarState
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.jar import Jar


class JarStateChange(Base):
    __tablename__ = "jar_state_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jar_id: Mapped[int] = mapped_column(
        ForeignKey("jar.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Null when the jar was created: there is no state it came from.
    from_state: Mapped[JarState | None] = mapped_column(
        Enum(JarState, native_enum=False, validate_strings=True, length=16)
    )
    to_state: Mapped[JarState] = mapped_column(
        Enum(JarState, native_enum=False, validate_strings=True, length=16),
        nullable=False,
    )

    changed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, index=True
    )
    note: Mapped[str | None] = mapped_column(Text)

    jar: Mapped[Jar] = relationship(back_populates="state_changes")

    def __repr__(self) -> str:
        return (
            f"JarStateChange(jar_id={self.jar_id!r}, "
            f"{self.from_state!r} -> {self.to_state!r})"
        )
