"""A bake: a recipe version actually made, and how it turned out.

A bake points at a *version*, never at a recipe, so editing the recipe
afterwards cannot rewrite what was baked (CLAUDE.md). The recipe's stages are
copied into `bake_stage_log` when the bake starts, for the same reason: the
plan a loaf was baked to is part of the record, not a live reference.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column
from app.models.enums import BakeMethod, BakeStatus
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.jar import Jar
    from app.models.recipe import EquipmentProgram, RecipeVersion


def _enum(python_enum: type, length: int = 16) -> Enum:
    return Enum(
        python_enum, native_enum=False, validate_strings=True, length=length
    )


class Bake(Base):
    __tablename__ = "bake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # RESTRICT: a version with a bake against it must stay readable.
    recipe_version_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Which jar raised it. Nullable: a bread-maker loaf on commercial yeast
    # is still worth logging.
    jar_id: Mapped[int | None] = mapped_column(
        ForeignKey("jar.id", ondelete="SET NULL"), index=True
    )

    method: Mapped[BakeMethod] = mapped_column(
        _enum(BakeMethod), nullable=False, default=BakeMethod.OVEN
    )
    equipment_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipment_program.id", ondelete="SET NULL")
    )
    crust_setting: Mapped[str | None] = mapped_column(String(40))
    loaf_size: Mapped[str | None] = mapped_column(String(40))

    oven_temp_c: Mapped[float | None] = mapped_column(Float)
    bake_min: Mapped[int | None] = mapped_column(Integer)
    # What the percentages were scaled against for this loaf.
    total_flour_g: Mapped[float | None] = mapped_column(Float)

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    status: Mapped[BakeStatus] = mapped_column(
        _enum(BakeStatus), nullable=False, default=BakeStatus.PLANNED
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    version: Mapped[RecipeVersion] = relationship(back_populates="bakes")
    jar: Mapped[Jar | None] = relationship(back_populates="bakes")
    program: Mapped[EquipmentProgram | None] = relationship()

    stage_logs: Mapped[list[BakeStageLog]] = relationship(
        back_populates="bake",
        cascade="all, delete-orphan",
        order_by="BakeStageLog.seq",
    )
    result: Mapped[BakeResult | None] = relationship(
        back_populates="bake", cascade="all, delete-orphan", uselist=False
    )

    @property
    def recipe(self):
        return self.version.recipe

    @property
    def label(self) -> str:
        return f"{self.version.recipe.name} {self.version.label}"

    @property
    def at(self) -> datetime:
        """When this bake belongs on a timeline: started if it has, else made."""
        return self.started_at or self.created_at

    def __repr__(self) -> str:
        return f"Bake(id={self.id!r}, status={self.status!r})"


class BakeStageLog(Base):
    """One stage of the plan, and when it actually happened."""

    __tablename__ = "bake_stage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bake_id: Mapped[int] = mapped_column(
        ForeignKey("bake.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Which generated step of the planner this came from ("levain_rise",
    #: "bake"), where a planner laid the bake out. Null for a stage copied
    #: straight from a recipe version, whose names are the baker's own.
    step_key: Mapped[str | None] = mapped_column(String(32))
    # Copied from the recipe version, so the plan survives a recipe edit.
    planned_min: Mapped[int | None] = mapped_column(Integer)
    #: What the timing model predicted for this step *before* the jar's own
    #: measured correction was applied, where the two differ. Only a rise
    #: has one. Keeping it is what lets a levain that peaked be read as a
    #: fresh measurement of the jar rather than a measurement of the
    #: correction already in force.
    model_min: Mapped[int | None] = mapped_column(Integer)
    planned_temp_c: Mapped[float | None] = mapped_column(Float)
    # Back-scheduling fills this in; v1 leaves it null (docs/dev/TODO-v1.md).
    planned_start: Mapped[datetime | None] = mapped_column(UtcDateTime)
    #: How long before this step the oven wants turning on. Set on a bake
    #: step whose method needs it, from the settings, when the plan is
    #: written down — copied for the same reason the durations are: the
    #: plan a loaf was baked to is part of the record, so changing the
    #: setting moves the next bake rather than the one in the oven.
    #:
    #: The preheat is deliberately *not* a step. It runs alongside the final
    #: proof, and a step in the chain would push the bake back by its own
    #: length. Null means no heads-up: the bread maker, a stage copied
    #: straight from a recipe, and every bake made before this existed —
    #: including one that already carries a preheat step by hand.
    preheat_lead_min: Mapped[int | None] = mapped_column(Integer)
    #: Stretch-and-folds during a bulk ferment: how many sets, and how far
    #: apart, counted from when the bulk began. Set on a bulk step from the
    #: settings when the bake is written down; null means no reminders.
    #: Not steps of their own for the reason the preheat is not: a fold is
    #: something done *during* the bulk, not something the bulk waits for.
    fold_sets: Mapped[int | None] = mapped_column(Integer)
    fold_every_min: Mapped[int | None] = mapped_column(Integer)
    #: How long the lid stays on, for a bake in a lidded pot. Set on the
    #: bake step of a pot bake; null everywhere else, including a recipe
    #: that already splits its bake into covered and uncovered stages.
    lid_off_after_min: Mapped[int | None] = mapped_column(Integer)

    #: Needs doing, so it is worth an alert at its start.
    hands_on: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    #: Minds nobody being there until it ends, so it is worth an alert then.
    must_be_home: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    actual_start: Mapped[datetime | None] = mapped_column(UtcDateTime)
    actual_end: Mapped[datetime | None] = mapped_column(UtcDateTime)
    #: Answered only for a rise that was asked about when it ended: True if
    #: it was at its peak, False if it was used anyway. Null means unasked.
    #: A True here with `planned_min` and `actual_min` is one measurement of
    #: how fast this jar really is.
    at_peak: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)

    bake: Mapped[Bake] = relationship(back_populates="stage_logs")
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="stage_log", cascade="all, delete-orphan"
    )

    @property
    def is_running(self) -> bool:
        return self.actual_start is not None and self.actual_end is None

    @property
    def is_done(self) -> bool:
        return self.actual_end is not None

    @property
    def actual_min(self) -> int | None:
        """How long it really took, in whole minutes."""
        if self.actual_start is None or self.actual_end is None:
            return None
        return round((self.actual_end - self.actual_start).total_seconds() / 60)

    @property
    def model_ratio(self) -> float | None:
        """How much slower than the bare model this rise really was.

        The number `services.learning` averages: 1.2 means this jar took a
        fifth longer to peak than the model expects of any jar.
        """
        actual = self.actual_min
        base = self.model_min or self.planned_min
        if actual is None or not base or self.at_peak is not True:
            return None
        return actual / base

    @property
    def planned_end(self) -> datetime | None:
        """When the plan says this step finishes."""
        if self.planned_start is None or self.planned_min is None:
            return None
        return self.planned_start + timedelta(minutes=self.planned_min)

    @property
    def is_planned(self) -> bool:
        return self.planned_start is not None

    @property
    def preheat_at(self) -> datetime | None:
        """When the oven has to go on for this step to be baked on time.

        The arithmetic only; whether it is still worth saying is
        `followalong.preheat_moment`.
        """
        if self.planned_start is None or not self.preheat_lead_min:
            return None
        return self.planned_start - timedelta(minutes=self.preheat_lead_min)

    @property
    def drift_min(self) -> int | None:
        """Actual minus planned. The interesting number on a second attempt."""
        actual = self.actual_min
        if actual is None or self.planned_min is None:
            return None
        return actual - self.planned_min

    def __repr__(self) -> str:
        return f"BakeStageLog(seq={self.seq!r}, name={self.name!r})"


class BakeResult(Base):
    """How the loaf turned out. One per bake."""

    __tablename__ = "bake_result"
    __table_args__ = (
        UniqueConstraint("bake_id", name="one_result_per_bake"),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="rating_one_to_five",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bake_id: Mapped[int] = mapped_column(
        ForeignKey("bake.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rating: Mapped[int | None] = mapped_column(Integer)
    crust: Mapped[str | None] = mapped_column(String(120))
    crumb: Mapped[str | None] = mapped_column(String(120))
    taste: Mapped[str | None] = mapped_column(String(120))
    rise: Mapped[str | None] = mapped_column(String(120))
    # The whole point of a lab notebook: what to change next time.
    next_time: Mapped[str | None] = mapped_column(Text)
    created_at = created_at_column()

    bake: Mapped[Bake] = relationship(back_populates="result")

    def __repr__(self) -> str:
        return f"BakeResult(bake_id={self.bake_id!r}, rating={self.rating!r})"
