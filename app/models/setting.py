"""Key/value user settings (display temperature unit, etc.)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Display units. Temperatures are stored in Celsius and weights in grams;
# these say how to show them. Fahrenheit by default because that is the
# kitchen this runs in; grams because that is how the rye recipes are written.
DEFAULT_SETTINGS = {"temp_unit": "F", "weight_unit": "g"}


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"Setting(key={self.key!r}, value={self.value!r})"
