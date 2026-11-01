"""A feeding: starter + flour + water, in grams."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, utcnow
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.jar import Jar


class Feeding(Base):
    __tablename__ = "feeding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jar_id: Mapped[int] = mapped_column(
        ForeignKey("jar.id", ondelete="CASCADE"), nullable=False, index=True
    )

    fed_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, index=True
    )

    # Grams throughout (CLAUDE.md). Float, not Integer: kitchen scales do
    # tenths, and 12.5 g of starter is a normal thing to write down.
    starter_g: Mapped[float] = mapped_column(Float, nullable=False)
    flour_g: Mapped[float] = mapped_column(Float, nullable=False)
    water_g: Mapped[float] = mapped_column(Float, nullable=False)

    flour_type: Mapped[str | None] = mapped_column(String(80))

    # Celsius in the database; displayed in the user's unit.
    water_temp_c: Mapped[float | None] = mapped_column(Float)
    ambient_temp_c: Mapped[float | None] = mapped_column(Float)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()

    jar: Mapped[Jar] = relationship(back_populates="feedings")

    def __repr__(self) -> str:
        return (
            f"Feeding(jar_id={self.jar_id!r}, fed_at={self.fed_at!r}, "
            f"{self.starter_g}:{self.flour_g}:{self.water_g})"
        )
