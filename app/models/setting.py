"""Key/value user settings (display temperature unit, etc.)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Display unit defaults to Fahrenheit even though we store Celsius.
DEFAULT_SETTINGS = {"temp_unit": "F"}


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"Setting(key={self.key!r}, value={self.value!r})"
