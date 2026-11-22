"""Busy blocks expanded into real instants.

A recurring block is a weekly pattern on the local clock; this turns it into
the actual stretches of UTC time it covers in a given window, which is what
the ribbon shades and the planner checks against.

The whole difficulty is the two Sundays a year when local time is not a
straight line. The rule here is that **a recurring block means wall-clock
time**: "Sleep 02:00–10:00" is however long it takes the clock to get from
two to ten. On the March Sunday that is seven hours of real time, and on the
November Sunday it is nine. That falls out of doing the arithmetic on naive
local datetimes and only then attaching the zone — which is why it is done
that way here rather than by adding a duration to an aware instant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.busy_block import MINUTES_PER_DAY, BusyBlock


@dataclass(frozen=True)
class BusyInterval:
    """One stretch of unavailable time, in UTC, and what it is called."""

    start: datetime
    end: datetime
    label: str

    def covers(self, moment: datetime) -> bool:
        """Half-open: a feed exactly at the end of a block is free."""
        return self.start <= moment < self.end

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and self.end > start


def list_blocks(
    session: Session, *, include_archived: bool = False
) -> list[BusyBlock]:
    stmt = select(BusyBlock).order_by(
        BusyBlock.archived, BusyBlock.start_minute, BusyBlock.label
    )
    if not include_archived:
        stmt = stmt.where(BusyBlock.archived.is_(False))
    return list(session.scalars(stmt))


def get_block(session: Session, block_id: int) -> BusyBlock | None:
    return session.get(BusyBlock, block_id)


def _local_midnight_naive(moment: datetime, tz: tzinfo) -> datetime:
    local = moment.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _wall_to_utc(naive_local: datetime, tz: tzinfo) -> datetime:
    """Read a local wall-clock reading as an instant.

    On the Sunday the clocks go forward there is no 02:30 at all, and on the
    Sunday they go back there are two. `fold=0` takes the first, which is the
    reading a person means when they write a time down: the one that comes
    first in the day they are living through.
    """
    return naive_local.replace(tzinfo=tz, fold=0).astimezone(UTC)


def _recurring_intervals(
    block: BusyBlock, start: datetime, end: datetime, tz: tzinfo
) -> list[BusyInterval]:
    duration = timedelta(minutes=block.duration_min)
    mask = int(block.weekday_mask or 0)
    if not mask:
        return []

    # A block that began yesterday can still be running when the window
    # opens, and one starting on the window's last local day can run past
    # it, so the walk is a day wider at each end than the window itself.
    day = (_local_midnight_naive(start, tz) - timedelta(days=1)).date()
    last_day = (_local_midnight_naive(end, tz) + timedelta(days=1)).date()

    found: list[BusyInterval] = []
    while day <= last_day:
        if mask & (1 << day.weekday()):
            opens_naive = datetime.combine(day, datetime.min.time()) + timedelta(
                minutes=int(block.start_minute or 0) % MINUTES_PER_DAY
            )
            # Wall-clock arithmetic first, zone second: see the module note.
            opens = _wall_to_utc(opens_naive, tz)
            closes = _wall_to_utc(opens_naive + duration, tz)
            if opens < end and closes > start:
                found.append(
                    BusyInterval(start=opens, end=closes, label=block.label)
                )
        day += timedelta(days=1)
    return found


def busy_intervals(
    session: Session, start: datetime, end: datetime, tz: tzinfo
) -> list[BusyInterval]:
    """Every unavailable stretch overlapping [start, end), soonest first.

    Blocks are not merged even where they overlap: "Sleep" and "Work" are
    different reasons to be unavailable, and the ribbon says which.
    """
    found: list[BusyInterval] = []

    for block in list_blocks(session):
        if block.is_recurring:
            found.extend(_recurring_intervals(block, start, end, tz))
        elif block.start_utc is not None and block.end_utc is not None:
            if block.start_utc < end and block.end_utc > start:
                found.append(
                    BusyInterval(
                        start=block.start_utc,
                        end=block.end_utc,
                        label=block.label,
                    )
                )

    found.sort(key=lambda one: (one.start, one.end, one.label))
    return found


# --- Asking questions of them -------------------------------------------


def covering(
    intervals: list[BusyInterval], moment: datetime
) -> BusyInterval | None:
    """The block a given instant falls inside, if any."""
    for interval in intervals:
        if interval.covers(moment):
            return interval
    return None


def is_busy(intervals: list[BusyInterval], moment: datetime) -> bool:
    return covering(intervals, moment) is not None


def overlapping(
    intervals: list[BusyInterval], start: datetime, end: datetime
) -> list[BusyInterval]:
    """Every block a stretch of time runs into.

    A zero-length stretch — a hands-on step that takes no time, or an instant
    being tested — is treated as the instant itself rather than as nothing,
    so it still reports the block it lands in.
    """
    if end <= start:
        return [one for one in intervals if one.covers(start)]
    return [one for one in intervals if one.overlaps(start, end)]


def next_free(
    intervals: list[BusyInterval],
    moment: datetime,
    *,
    needs: timedelta = timedelta(0),
    limit: datetime | None = None,
) -> datetime | None:
    """The first instant from `moment` with `needs` of clear time after it.

    Walks forward to the end of whichever block is in the way and tries
    again, because stepping out of "Sleep" can land inside "Work". Returns
    `moment` itself when it is already free, and None when nothing inside
    `limit` is long enough — better than handing back a time that does not
    actually work.
    """
    candidate = moment
    # Each pass clears at least one block, so this cannot spin: the bound is
    # a guard against a pathological set of overlapping blocks, not a guess.
    for _ in range(len(intervals) * 2 + 2):
        if limit is not None and candidate > limit:
            return None
        clashes = overlapping(intervals, candidate, candidate + needs)
        if not clashes:
            return candidate
        candidate = max(one.end for one in clashes)
    return None
