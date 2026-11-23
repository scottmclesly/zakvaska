"""A starter jar: the central object in the notebook."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column
from app.models.enums import JarOrigin, JarState
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.bake import Bake
    from app.models.feeding import Feeding
    from app.models.jar_state_change import JarStateChange
    from app.models.observation import Observation

# Defaults from CLAUDE.md's data model: twice a day on the counter, weekly
# in the fridge.
DEFAULT_ROOM_INTERVAL_H = 12
DEFAULT_FRIDGE_INTERVAL_H = 168

#: The silicone lids Scott's real jars wear, so the drawn jar can match the
#: one on the counter. Ten is a row of swatches on a phone without wrapping
#: badly, and the form offers a colour picker for anything not here.
#:
#: Chosen to read on both themes: no pure white or pure black, because the
#: lid is drawn against a surface that is one or the other.
CAP_PRESETS: tuple[tuple[str, str], ...] = (
    ("black", "#23252a"),
    ("white", "#f2efe8"),
    ("grey", "#8c8984"),
    ("red", "#c0392b"),
    ("orange", "#d2691e"),
    ("yellow", "#e3b92f"),
    ("green", "#4a8f5b"),
    ("blue", "#2f6f9f"),
    ("purple", "#7d5ba6"),
    ("pink", "#d2719a"),
)


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

    # How often this jar is fed when it is out on the counter. Null means
    # "use the app's setting", which is the usual case — a per-jar number is
    # for the jar that is deliberately on a different rhythm.
    #
    # This is what drives the planned feeds on the ribbon, and it supersedes
    # `feed_interval_room_h` for an active jar that has been fed: the
    # interval stays as the fallback for a jar with no plan yet, and as the
    # only answer for a jar in the fridge.
    feeds_per_day: Mapped[int | None] = mapped_column(Integer)

    feed_interval_room_h: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_ROOM_INTERVAL_H
    )
    feed_interval_fridge_h: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_FRIDGE_INTERVAL_H
    )

    # The time one planned feed should land at; every later planned feed
    # repeats from it at the jar's cycle length. Null means the plan simply
    # follows the last feed. Moving a planned feed writes this, which is
    # what keeps the whole later chain aligned rather than drifting.
    schedule_anchor_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)

    # Lineage: a jar split off from another keeps the thread back to it.
    parent_jar_id: Mapped[int | None] = mapped_column(
        ForeignKey("jar.id", ondelete="SET NULL")
    )
    # The purchased Soviet culture is the control in Scott's experiment.
    is_control: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # The colour of this jar's real silicone lid, as "#rrggbb". Null means
    # the jar is drawn with the muted grey lid it has always had — the
    # colour is a way of telling two jars apart, not something every jar
    # needs. See CAP_PRESETS and `routes.forms.opt_color`.
    cap_color: Mapped[str | None] = mapped_column(String(7))

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
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="jar",
        cascade="all, delete-orphan",
        order_by="Alert.due_at.desc()",
    )
    # Archiving a jar must not take its bakes with it, so no cascade here.
    bakes: Mapped[list[Bake]] = relationship(
        back_populates="jar", order_by="Bake.created_at.desc()"
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
