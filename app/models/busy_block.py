"""Times the baker is not available — asleep, at work, out.

The app cannot usefully say "feed it at 04:00" to someone who is asleep at
04:00, and it cannot know that without being told. A busy block is that
telling: a shaded stripe on the ribbon and the planner, and the reason a
suggested feed time gets moved.

Recurring blocks are stored as **local wall-clock minutes**, not as instants.
"I sleep from two until ten" means the clock says two and the clock says ten,
which is seven hours of real time on the Sunday the clocks go forward and
nine on the Sunday they go back. Storing a UTC offset instead would quietly
shift the block twice a year, which is exactly the bug this notebook's
UTC-everywhere rule is usually there to prevent — so this is the one place
that rule reads the other way, and the service that expands these into UTC
is tested across both changeovers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column
from app.models.enums import BusyKind
from app.models.types import UtcDateTime

if TYPE_CHECKING:
    pass

MINUTES_PER_DAY = 24 * 60

#: Bit per weekday, Monday first, matching datetime.weekday().
MONDAY = 1 << 0
TUESDAY = 1 << 1
WEDNESDAY = 1 << 2
THURSDAY = 1 << 3
FRIDAY = 1 << 4
SATURDAY = 1 << 5
SUNDAY = 1 << 6

EVERY_DAY = 0b1111111
WEEKDAYS = MONDAY | TUESDAY | WEDNESDAY | THURSDAY | FRIDAY
WEEKENDS = SATURDAY | SUNDAY

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday_label(mask: int) -> str:
    """"Every day", "Mon–Fri", "Sat, Sun" — a mask as a person reads it."""
    mask &= EVERY_DAY
    if mask == EVERY_DAY:
        return "Every day"
    if mask == WEEKDAYS:
        return "Mon–Fri"
    if mask == WEEKENDS:
        return "Weekends"
    if mask == 0:
        return "No days"
    days = [name for index, name in enumerate(WEEKDAY_NAMES) if mask & (1 << index)]
    return ", ".join(days)


def weekday_indices(mask: int) -> tuple[int, ...]:
    """The weekdays in a mask, Monday 0. Jinja has no bitwise and, so the
    unpacking happens here rather than in the template."""
    mask = int(mask or 0) & EVERY_DAY
    return tuple(index for index in range(7) if mask & (1 << index))


def minutes_label(minutes: int) -> str:
    """Minutes from local midnight as a clock reading: 125 -> '02:05'."""
    whole = int(minutes) % MINUTES_PER_DAY
    return f"{whole // 60:02d}:{whole % 60:02d}"


class BusyBlock(Base):
    __tablename__ = "busy_block"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[BusyKind] = mapped_column(
        Enum(BusyKind, native_enum=False, validate_strings=True, length=16),
        nullable=False,
        default=BusyKind.RECURRING,
    )

    # --- Recurring: a weekly pattern in local wall-clock time ---
    #
    # Bitmask of weekdays the block starts on, and minutes from local
    # midnight. `end_minute` at or before `start_minute` means the block runs
    # past midnight into the next day, which is the common case here: Scott's
    # sleep starts at 02:00 and ends at 10:00, but "22:00 to 06:00" has to
    # work too.
    weekday_mask: Mapped[int | None] = mapped_column(Integer)
    start_minute: Mapped[int | None] = mapped_column(Integer)
    end_minute: Mapped[int | None] = mapped_column(Integer)

    # --- Once: a single stretch, stored in UTC like every other instant ---
    start_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)
    end_utc: Mapped[datetime | None] = mapped_column(UtcDateTime)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at = created_at_column()

    @property
    def is_recurring(self) -> bool:
        return self.kind is BusyKind.RECURRING

    @property
    def weekdays(self) -> tuple[int, ...]:
        """Which days it falls on, as indices a template can test against."""
        return weekday_indices(self.weekday_mask or 0)

    @property
    def duration_min(self) -> int:
        """How long a recurring block lasts, counted on the local clock.

        Equal start and end means the whole day: a block of no length at all
        is never what someone meant to enter.
        """
        if not self.is_recurring:
            return 0
        span = (int(self.end_minute or 0) - int(self.start_minute or 0)) % MINUTES_PER_DAY
        return span or MINUTES_PER_DAY

    @property
    def wraps_midnight(self) -> bool:
        return self.is_recurring and (
            int(self.end_minute or 0) <= int(self.start_minute or 0)
        )

    @property
    def when_label(self) -> str:
        """The whole schedule in one line, for the settings list."""
        if not self.is_recurring:
            return "once"
        times = (
            f"{minutes_label(self.start_minute or 0)}–"
            f"{minutes_label(self.end_minute or 0)}"
        )
        suffix = " (next day)" if self.wraps_midnight else ""
        return f"{weekday_label(self.weekday_mask or 0)} {times}{suffix}"

    def __repr__(self) -> str:
        return f"BusyBlock(id={self.id!r}, label={self.label!r}, {self.when_label})"
