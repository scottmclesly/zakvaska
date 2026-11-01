"""A starter jar: the central object in the notebook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column
from app.models.enums import JarOrigin, JarState

if TYPE_CHECKING:
    from app.models.feeding import Feeding
    from app.models.jar_state_change import JarStateChange
    from app.models.observation import Observation

# Defaults from CLAUDE.md's data model: twice a day on the counter, weekly
# in the fridge.
DEFAULT_ROOM_INTERVAL_H = 12
DEFAULT_FRIDGE_INTERVAL_H = 168


def _enum(python_enum: type) -> Enum:
    # native_enum=False keeps this a VARCHAR + CHECK, which SQLite and
    # Alembic's batch mode both handle without drama.
    return Enum(python_enum, native_enum=False, validate_strings=True, length=16)


class Jar(Base):
    __tablename__ = "jar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    origin: Mapped[JarOrigin] = mapped_column(_enum(JarOrigin), nullable=False)
    culture_name: Mapped[str | None] = mapped_column(String(120))
    flour_type: Mapped[str | None] = mapped_column(String(80))

    state: Mapped[JarState] = mapped_column(
        _enum(JarState), nullable=False, default=JarState.ACTIVE
    )

    feed_interval_room_h: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_ROOM_INTERVAL_H
    )
    feed_interval_fridge_h: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_FRIDGE_INTERVAL_H
    )

    # Lineage: a jar split off from another keeps the thread back to it.
    parent_jar_id: Mapped[int | None] = mapped_column(
        ForeignKey("jar.id", ondelete="SET NULL")
    )
    # The purchased Soviet culture is the control in Scott's experiment.
    is_control: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    parent: Mapped[Jar | None] = relationship(
        "Jar", remote_side="Jar.id", back_populates="children"
    )
    children: Mapped[list[Jar]] = relationship(
        "Jar", back_populates="parent", order_by="Jar.name"
    )

    feedings: Mapped[list[Feeding]] = relationship(
        back_populates="jar",
        cascade="all, delete-orphan",
        order_by="Feeding.fed_at.desc()",
    )
    observations: Mapped[list[Observation]] = relationship(
        back_populates="jar",
        cascade="all, delete-orphan",
        order_by="Observation.observed_at.desc()",
    )
    state_changes: Mapped[list[JarStateChange]] = relationship(
        back_populates="jar",
        cascade="all, delete-orphan",
        order_by="JarStateChange.changed_at.desc()",
    )

    @property
    def feed_interval_h(self) -> int | None:
        """Hours between feeds in the jar's current state, or None if it sleeps."""
        if self.state is JarState.ACTIVE:
            return self.feed_interval_room_h
        if self.state is JarState.FRIDGE:
            return self.feed_interval_fridge_h
        return None

    def __repr__(self) -> str:
        return f"Jar(id={self.id!r}, name={self.name!r}, state={self.state!r})"
