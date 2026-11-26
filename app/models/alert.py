"""Alerts: a jar that wants feeding, or a bake-day step that is due.

Rows are derived state, not a log: every one of them can be rebuilt from the
jars and their feedings, or from a bake's planned stage times. That is what
makes a restart safe — the scheduler recomputes from the database rather
than holding anything in memory.

One table for both kinds, because the lifecycle is the same and so is the
banner: fire, then acknowledge or snooze. Exactly one of `jar_id` and
`stage_log_id` is set, and which one it is says what the alert is about.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column
from app.models.enums import AlertKind
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    from app.models.bake import BakeStageLog
    from app.models.jar import Jar


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        # One alert per jar per due moment, and one per stage per due moment.
        # This is what lets the scheduler run every minute and stay
        # idempotent. SQLite treats NULLs as distinct in a unique index, so
        # the two constraints do not get in each other's way: a feeding
        # alert leaves `stage_log_id` null and a stage alert leaves
        # `jar_id` null.
        UniqueConstraint("jar_id", "kind", "due_at", name="one_per_due"),
        UniqueConstraint(
            "stage_log_id", "kind", "due_at", name="one_per_stage_due"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Set on a feeding alert. Null on a stage alert.
    jar_id: Mapped[int | None] = mapped_column(
        ForeignKey("jar.id", ondelete="CASCADE"), index=True
    )
    #: Set on a stage alert. Null on a feeding alert. CASCADE, because a
    #: stage log that is gone can have nothing outstanding against it.
    stage_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("bake_stage_log.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AlertKind] = mapped_column(
        Enum(AlertKind, native_enum=False, validate_strings=True, length=16),
        nullable=False,
        default=AlertKind.FEED_DUE,
    )

    # When the jar became (or becomes) due.
    due_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    # Set the moment the alert actually goes off. None means still pending.
    fired_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Set when dismissed, or automatically when the jar is fed.
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Pushes the trigger later without losing why the alert existed.
    snoozed_until: Mapped[datetime | None] = mapped_column(UtcDateTime)

    created_at = created_at_column()

    jar: Mapped[Jar | None] = relationship(back_populates="alerts")
    stage_log: Mapped[BakeStageLog | None] = relationship(
        back_populates="alerts"
    )

    @property
    def effective_due_at(self) -> datetime:
        """When this should go off, taking a snooze into account."""
        return self.snoozed_until or self.due_at

    @property
    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None

    @property
    def is_pending(self) -> bool:
        """Due in the future, not yet gone off."""
        return self.fired_at is None and self.acknowledged_at is None

    def is_snoozed_at(self, now: datetime) -> bool:
        return self.snoozed_until is not None and now < self.snoozed_until

    def is_showing_at(self, now: datetime) -> bool:
        """Fired, not dealt with, and not currently snoozed away."""
        return (
            self.fired_at is not None
            and self.acknowledged_at is None
            and not self.is_snoozed_at(now)
        )

    @property
    def is_about_a_bake(self) -> bool:
        return self.stage_log_id is not None

    @property
    def subject(self) -> str:
        """What to call this alert in one short phrase.

        A preheat is about the oven rather than about the step it is
        counted back from, so it does not borrow that step's name — being
        told "Bake" three quarters of an hour early would read as the
        bake being due. The sentence with the temperature and the minutes
        in it is `services.alerts.headline`, which knows the display unit.
        """
        if self.kind.is_preheat:
            return "Preheat the oven"
        if self.stage_log is not None:
            return self.stage_log.name
        return self.jar.name if self.jar is not None else "something"

    @property
    def url(self) -> str:
        """Where tapping the alert should take you, to deal with it."""
        if self.stage_log is not None:
            return f"/bakes/{self.stage_log.bake_id}"
        return f"/jars/{self.jar_id}/feed"

    def __repr__(self) -> str:
        return (
            f"Alert(jar_id={self.jar_id!r}, due_at={self.due_at!r}, "
            f"fired={self.fired_at is not None}, ack={self.is_acknowledged})"
        )
