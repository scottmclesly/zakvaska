"""An observation of how a jar is behaving between feeds."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, utcnow
from app.models.enums import BubbleLevel
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.jar import Jar


class Observation(Base):
    __tablename__ = "observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jar_id: Mapped[int] = mapped_column(
        ForeignKey("jar.id", ondelete="CASCADE"), nullable=False, index=True
    )

    observed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, index=True
    )

    # Height of the starter in the jar, and where it started after feeding.
    # rise_pct is derived from the pair, never stored (CLAUDE.md data model).
    start_height_mm: Mapped[float | None] = mapped_column(Float)
    height_mm: Mapped[float | None] = mapped_column(Float)

    bubbles: Mapped[BubbleLevel | None] = mapped_column(
        Enum(BubbleLevel, native_enum=False, validate_strings=True, length=16)
    )
    # Open vocabularies: suggested in the form, not constrained in the schema.
    smell: Mapped[str | None] = mapped_column(String(80))
    texture: Mapped[str | None] = mapped_column(String(80))

    notes: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()

    jar: Mapped[Jar] = relationship(back_populates="observations")

    def __repr__(self) -> str:
        return (
            f"Observation(jar_id={self.jar_id!r}, "
            f"observed_at={self.observed_at!r})"
        )
