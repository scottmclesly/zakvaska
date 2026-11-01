"""Feeding alerts.

Rows are derived state, not a log: every one of them can be rebuilt from the
jars and their feedings. That is what makes a restart safe — the scheduler
recomputes from the database rather than holding anything in memory.
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
    from app.models.jar import Jar


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        # One alert per jar per due moment. This is what lets the scheduler
        # run every minute and stay idempotent.
        UniqueConstraint("jar_id", "kind", "due_at", name="one_per_due"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jar_id: Mapped[int] = mapped_column(
        ForeignKey("jar.id", ondelete="CASCADE"), nullable=False, index=True
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

    jar: Mapped[Jar] = relationship(back_populates="alerts")

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

    def __repr__(self) -> str:
        return (
            f"Alert(jar_id={self.jar_id!r}, due_at={self.due_at!r}, "
            f"fired={self.fired_at is not None}, ack={self.is_acknowledged})"
        )
