"""Plots drawn from what has been logged: coordinates, not pictures.

The templates draw; this decides where. Kept apart so the fiddly arithmetic
can be tested without parsing an SVG: choosing axis steps that land on round
numbers, finding where the local day boundaries fall, and the awkward cases —
one lone reading, two readings at the same instant, a starter that sank
instead of rising.

Nothing here knows about the ORM. The callers hand over plain samples, which
keeps a chart testable from a list of numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

# --- Geometry -----------------------------------------------------------
#
# One fixed plot box, in the SVG's own user units, so stroke widths and type
# stay the size they are written as. The gutter on the left holds the axis
# figures; the strip underneath holds the dates.


@dataclass(frozen=True)
class PlotBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


# The viewBox is about the width the chart actually renders at, so the
# figures on the axes come out near the size they are written as instead of
# being scaled down to nothing on a phone.
PLOT = PlotBox(x=44.0, y=14.0, w=300.0, h=126.0)
VIEWBOX = "0 0 360 170"

# At most this many gridlines, or the plot turns into graph paper.
_MAX_BANDS = 6
_Y_STEPS = (10.0, 25.0, 50.0, 100.0, 200.0, 500.0, 1000.0)
# Hours between date ticks. The first one that fits across is used; four
# gaps is as many as "Sun 06:00" fits into the width without colliding.
_TICK_HOURS = (1, 2, 3, 6, 12, 24, 48, 72, 168, 336, 720)
_MAX_TICKS = 4


# --- What goes in -------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One reading: a value at an instant. Timestamps are UTC, as stored."""

    at: datetime
    value: float


@dataclass(frozen=True)
class SeriesInput:
    name: str
    samples: Sequence[Sample]
    is_control: bool = False


# --- What comes out -----------------------------------------------------


@dataclass(frozen=True)
class Point:
    at: datetime
    value: float
    x: float
    y: float


@dataclass(frozen=True)
class Line:
    name: str
    #: 1-based, and all the template needs to pick this line's colour.
    slot: int
    is_control: bool
    points: tuple[Point, ...]

    @property
    def polyline(self) -> str:
        """The `points` attribute of a <polyline>, ready to drop in."""
        return " ".join(f"{p.x:.2f},{p.y:.2f}" for p in self.points)

    @property
    def last(self) -> Point | None:
        return self.points[-1] if self.points else None

    @property
    def best(self) -> Point | None:
        return max(self.points, key=lambda p: p.value) if self.points else None


@dataclass(frozen=True)
class Gridline:
    value: float
    y: float
    label: str
    #: The "it doubled" line, which is what this chart gets read for.
    is_doubled: bool = False
    #: Where it started, so a jar that sank reads as having sunk.
    is_baseline: bool = False


@dataclass(frozen=True)
class XTick:
    at: datetime
    x: float
    label: str


@dataclass(frozen=True)
class RiseChart:
    lines: tuple[Line, ...]
    gridlines: tuple[Gridline, ...]
    ticks: tuple[XTick, ...]
    y_min: float
    y_max: float
    first_at: datetime
    last_at: datetime
    plot: PlotBox = PLOT
    viewbox: str = VIEWBOX

    @property
    def sample_count(self) -> int:
        return sum(len(line.points) for line in self.lines)


# --- Axes ---------------------------------------------------------------


def _y_bounds(values: Sequence[float]) -> tuple[float, float, float]:
    """Round axis limits that contain the data, with a step to label by.

    100% is always on the chart whether or not anything got there: "did it
    double" is the question the plot is being asked, so the answer needs a
    line to be measured against. Zero likewise, so a jar that sank reads as
    having sunk rather than just being low.
    """
    high = max(max(values), 100.0)
    low = min(min(values), 0.0)

    for step in _Y_STEPS:
        top = math.ceil(high / step) * step
        bottom = math.floor(low / step) * step
        if (top - bottom) / step <= _MAX_BANDS:
            return bottom, top, step

    step = _Y_STEPS[-1]
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def _local_midnight(moment: datetime, tz: tzinfo) -> datetime:
    """The start of the local day `moment` falls in."""
    local = moment.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _tick_step_hours(span_hours: float) -> int:
    for hours in _TICK_HOURS:
        if span_hours / hours <= _MAX_TICKS:
            return hours
    return _TICK_HOURS[-1]


def _tick_times(
    first: datetime, last: datetime, tz: tzinfo
) -> tuple[list[datetime], int]:
    """Round local instants to label the time axis with.

    Aligned to the local clock rather than to the first reading: "Sun 06:00"
    is a time a person recognises, and 05:43 is not.
    """
    span_hours = (last - first).total_seconds() / 3600
    step = _tick_step_hours(span_hours)
    ticks: list[datetime] = []

    if step < 24:
        at = _local_midnight(first, tz)
        while at < first:
            at += timedelta(hours=step)
        while at <= last:
            ticks.append(at)
            at += timedelta(hours=step)
    else:
        # Walk whole local days, so a tick stays at midnight across a clock
        # change rather than drifting to 23:00.
        days = step // 24
        day = _local_midnight(first, tz).date()
        while True:
            at = datetime.combine(
                day, datetime.min.time(), tzinfo=tz
            )
            if at > last:
                break
            if at >= first:
                ticks.append(at)
            day += timedelta(days=days)

    return ticks, step


def _tick_label(at: datetime, step_hours: int) -> str:
    if step_hours < 24:
        return at.strftime("%a %H:%M")
    return f"{at.day} {at:%b}"


def _trim(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text or "0"


# --- The chart ----------------------------------------------------------


def rise_chart(
    inputs: Sequence[SeriesInput], *, tz: tzinfo, plot: PlotBox = PLOT
) -> RiseChart | None:
    """Rise against time, one line per jar, overlaid for comparison.

    None when there is nothing worth drawing. Two readings is the threshold:
    a single dot is not a trend, and the drawn jar already says how full it
    is, so a chart of one point would only add furniture.
    """
    series = [one for one in inputs if one.samples]
    total = sum(len(one.samples) for one in series)
    if total < 2:
        return None

    moments = [sample.at for one in series for sample in one.samples]
    values = [sample.value for one in series for sample in one.samples]
    first, last = min(moments), max(moments)

    y_min, y_max, y_step = _y_bounds(values)
    y_span = y_max - y_min

    def y_for(value: float) -> float:
        # SVG counts down from the top; the axis counts up.
        return plot.bottom - (value - y_min) / y_span * plot.h

    seconds = (last - first).total_seconds()

    def x_for(at: datetime) -> float:
        if seconds <= 0:
            # Everything at one instant: a column in the middle beats a
            # column squashed against the axis.
            return plot.x + plot.w / 2
        return plot.x + (at - first).total_seconds() / seconds * plot.w

    lines: list[Line] = []
    for slot, one in enumerate(series, start=1):
        ordered = sorted(one.samples, key=lambda s: s.at)
        lines.append(
            Line(
                name=one.name,
                slot=slot,
                is_control=one.is_control,
                points=tuple(
                    Point(
                        at=sample.at,
                        value=sample.value,
                        x=x_for(sample.at),
                        y=y_for(sample.value),
                    )
                    for sample in ordered
                ),
            )
        )

    gridlines: list[Gridline] = []
    steps = int(round(y_span / y_step))
    for index in range(steps + 1):
        value = y_min + index * y_step
        gridlines.append(
            Gridline(
                value=value,
                y=y_for(value),
                label=f"{_trim(value)}%",
                is_doubled=abs(value - 100.0) < 1e-9,
                is_baseline=abs(value) < 1e-9,
            )
        )

    moments_ticks, step_hours = _tick_times(first, last, tz)
    ticks = [
        XTick(at=at, x=x_for(at), label=_tick_label(at, step_hours))
        for at in moments_ticks
    ]
    if len(ticks) < 2:
        # Too short or too tight a span to land on round numbers; label the
        # ends, which is better than labelling nothing.
        ticks = [
            XTick(at=first, x=x_for(first), label=_tick_label(first, 1)),
            XTick(at=last, x=x_for(last), label=_tick_label(last, 1)),
        ]
        if seconds <= 0:
            ticks = ticks[:1]

    return RiseChart(
        lines=tuple(lines),
        gridlines=tuple(gridlines),
        ticks=tuple(ticks),
        y_min=y_min,
        y_max=y_max,
        first_at=first,
        last_at=last,
        plot=plot,
        viewbox=VIEWBOX,
    )


# --- Bars of elapsed time -----------------------------------------------
#
# The bread maker's programs and a recipe's stages are both "these phases,
# in this order, for these many minutes", so one tested layout serves both.


@dataclass(frozen=True)
class Segment:
    name: str
    #: Which kind of phase: the template's hook for a colour.
    key: str
    minutes: float | None
    start_min: float
    pct: float
    #: True when the phase has no time against it, so it is drawn to no
    #: scale and says so rather than silently lying about its width.
    unknown: bool = False

    @property
    def duration_label(self) -> str:
        if self.minutes is None:
            return "no time set"
        if self.minutes < 1:
            return f"{round(self.minutes * 60)} sec"
        if self.minutes < 60:
            return f"{_trim(self.minutes)} min"
        hours, rest = divmod(int(round(self.minutes)), 60)
        return f"{hours} h {rest:02d} min" if rest else f"{hours} h"

    @property
    def title(self) -> str:
        return f"{self.name} — {self.duration_label}"


@dataclass(frozen=True)
class TimeBar:
    segments: tuple[Segment, ...]
    total_min: float

    @property
    def total_label(self) -> str:
        hours, minutes = divmod(int(round(self.total_min)), 60)
        return f"{hours}:{minutes:02d}"

    @property
    def has_unknown(self) -> bool:
        return any(segment.unknown for segment in self.segments)


#: Below this share of a stated total, the phases that are listed say so
#: little about the program that a bar would be mostly filler.
_MIN_ACCOUNTED = 0.25


def time_bar(
    phases: Sequence[tuple[str, str, float | None]],
    *,
    keep_unknown: bool = False,
    total_min: float | None = None,
) -> TimeBar | None:
    """Lay phases out along a bar in proportion to their minutes.

    `phases` is (name, key, minutes); minutes of None means the machine has
    no such phase at all — the manual's "x" — and it is dropped, unless
    `keep_unknown`, which is for a recipe stage that is a real step someone
    simply has not timed yet.

    `total_min` is a length known from elsewhere — the manual's own figure
    for a program, which does not always equal its segments added up. Time
    it does not account for becomes a segment of its own, because a bar
    normalised to the listed phases alone would show a thirty-second stir
    filling a three-hour program.

    None when there is no time to be in proportion to, or when so little of
    a stated total is broken down that the bar would say nothing.
    """
    timed = [
        (name, key, float(minutes))
        for name, key, minutes in phases
        if minutes is not None and minutes > 0
    ]
    if not timed:
        return None

    listed = sum(minutes for _, _, minutes in timed)
    unlisted = 0.0
    if total_min:
        if listed / total_min < _MIN_ACCOUNTED:
            return None
        # A minute or two of rounding is not worth a segment.
        gap = float(total_min) - listed
        if gap > max(total_min * 0.02, 1.0):
            unlisted = gap

    total = listed + unlisted
    # An untimed stage is drawn as a thin slice: wide enough to read, small
    # enough that it cannot be mistaken for a phase of its own length.
    unknown_min = max(total * 0.04, 1.0)

    segments: list[Segment] = []
    running = 0.0
    for name, key, minutes in phases:
        if minutes is None or minutes <= 0:
            if not keep_unknown:
                continue
            segments.append(
                Segment(
                    name=name,
                    key=key,
                    minutes=None,
                    start_min=running,
                    pct=unknown_min / total * 100,
                    unknown=True,
                )
            )
            continue
        segments.append(
            Segment(
                name=name,
                key=key,
                minutes=float(minutes),
                start_min=running,
                pct=float(minutes) / total * 100,
            )
        )
        running += float(minutes)

    if unlisted:
        segments.append(
            Segment(
                name="Not broken down",
                key="unlisted",
                minutes=unlisted,
                start_min=running,
                pct=unlisted / total * 100,
            )
        )

    return TimeBar(segments=tuple(segments), total_min=total)
