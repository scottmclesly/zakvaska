"""The feeding ribbon: a jar's cycle laid out along a time axis.

Where `charts.py` plots what was measured, this lays out what is *going to
happen*: the rise each feed set off, where the next feeds are planned, and
which of them land in the hours Scott is asleep. One row per jar, and when
there are several they share one time axis so the two jars can be read
against each other.

Same bargain as `charts.py` — this works out coordinates and the Jinja
partial draws them, so the fiddly arithmetic is testable without parsing an
SVG. It knows about `timing` (the curve's shape is the model's, not a
drawing decision) but nothing about the ORM: callers hand over plain marks.

The rise curve is drawn in pieces, one per readiness band, because a single
polyline can only be one colour and the colour is the point: rising, at its
peak, still good, going over, hungry.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from app.services import timing
from app.services.charts import PlotBox
from app.services.timing import Band

# --- Geometry -----------------------------------------------------------
#
# Written in the SVG's own user units at about the width it renders, so the
# type comes out the size it is written as rather than being scaled away on
# a phone. The viewBox height is worked out from the number of rows.

WIDTH = 360.0
#: Left and right margins. Narrow: the ribbon wants its width for time.
MARGIN_X = 6.0
#: Above the first row, for the day labels.
HEADER_H = 14.0
#: One jar's row: a name line, then the band the curve is drawn in.
ROW_LABEL_H = 13.0
ROW_CURVE_H = 42.0
ROW_GAP_H = 8.0
#: The strip under the last row that carries the clock times.
AXIS_H = 20.0

ROW_H = ROW_LABEL_H + ROW_CURVE_H + ROW_GAP_H

#: How often the curve is sampled. Fine enough that the peak reads as round.
SAMPLE_MIN = 10.0
#: At most this many clock labels across, or they collide.
MAX_TICKS = 8
_TICK_HOURS = (1, 2, 3, 4, 6, 8, 12, 24)


# --- What goes in -------------------------------------------------------


@dataclass(frozen=True)
class FeedMark:
    """A feed that happened, and the rise it set off."""

    at: datetime
    peak_h: float
    ratio_label: str | None = None
    temp_assumed: bool = False


@dataclass(frozen=True)
class PlannedMark:
    """A feed that has not happened yet."""

    at: datetime
    index: int
    #: The busy block it lands in, if it lands in one.
    busy_label: str | None = None
    #: Where it could move to instead, and what to feed it there.
    move_to: datetime | None = None
    move_ratio_label: str | None = None


@dataclass(frozen=True)
class ObservationMark:
    """A height that was actually measured, to sit against the prediction."""

    at: datetime
    rise_pct: float


@dataclass(frozen=True)
class BusyMark:
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True)
class RibbonSeries:
    """One jar's worth of ribbon."""

    name: str
    jar_id: int
    feeds: Sequence[FeedMark] = ()
    planned: Sequence[PlannedMark] = ()
    observations: Sequence[ObservationMark] = ()
    is_control: bool = False
    #: Shown instead of a curve when there is nothing to draw.
    note: str | None = None


# --- What comes out -----------------------------------------------------


@dataclass(frozen=True)
class CurveSegment:
    """One band's worth of a rise curve, as a ready-to-drop polyline."""

    band: Band
    points: tuple[tuple[float, float], ...]

    @property
    def polyline(self) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in self.points)

    @property
    def band_key(self) -> str:
        return self.band.value


@dataclass(frozen=True)
class RiseCurve:
    """The predicted rise after one feed, in bands."""

    segments: tuple[CurveSegment, ...]
    feed: FeedMark
    #: Where the feed itself sits, so the marker lands on the baseline.
    x: float
    #: The peak, for the tick above the curve. None when it is off-window.
    peak_x: float | None
    peak_at: datetime
    #: The y the curve rises from, worked out by the layout.
    baseline: float

    @property
    def has_shape(self) -> bool:
        return any(len(one.points) > 1 for one in self.segments)

    @property
    def area(self) -> str:
        """The same curve closed back along the baseline, for a soft fill."""
        points = [point for one in self.segments for point in one.points]
        if len(points) < 2:
            return ""
        body = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        return (
            f"{points[0][0]:.2f},{self.baseline:.2f} {body} "
            f"{points[-1][0]:.2f},{self.baseline:.2f}"
        )


@dataclass(frozen=True)
class PlannedPoint:
    mark: PlannedMark
    x: float

    @property
    def clashes(self) -> bool:
        return self.mark.busy_label is not None


@dataclass(frozen=True)
class ObservationPoint:
    mark: ObservationMark
    x: float
    y: float


@dataclass(frozen=True)
class RibbonRow:
    """One jar, laid out."""

    name: str
    jar_id: int
    slot: int
    is_control: bool
    curves: tuple[RiseCurve, ...]
    planned: tuple[PlannedPoint, ...]
    observations: tuple[ObservationPoint, ...]
    #: The band this row's curve is drawn in.
    top: float
    bottom: float
    label_y: float
    note: str | None = None

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def clashes(self) -> tuple[PlannedPoint, ...]:
        """The planned feeds landing in a busy block, for the warning badges."""
        return tuple(one for one in self.planned if one.clashes)


@dataclass(frozen=True)
class Tick:
    at: datetime
    x: float
    label: str
    #: Local midnight: drawn stronger and carries the day name.
    is_day_start: bool = False
    day_label: str = ""


@dataclass(frozen=True)
class BusyShade:
    x1: float
    x2: float
    label: str

    @property
    def width(self) -> float:
        return self.x2 - self.x1


@dataclass(frozen=True)
class Ribbon:
    rows: tuple[RibbonRow, ...]
    ticks: tuple[Tick, ...]
    busy: tuple[BusyShade, ...]
    start: datetime
    end: datetime
    now: datetime
    now_x: float
    plot: PlotBox
    viewbox: str
    axis_y: float

    @property
    def span_h(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def clashes(self) -> tuple[PlannedPoint, ...]:
        return tuple(one for row in self.rows for one in row.clashes)


# --- Laying it out ------------------------------------------------------


def _tick_step_hours(span_h: float) -> int:
    for hours in _TICK_HOURS:
        if span_h / hours <= MAX_TICKS:
            return hours
    return _TICK_HOURS[-1]


def _ticks(
    start: datetime, end: datetime, tz: tzinfo, x_for
) -> tuple[Tick, ...]:
    """Clock-aligned ticks, so the labels are times a person recognises.

    Walked as local wall-clock hours from local midnight and only then
    converted, which is what keeps a midnight tick at midnight across a
    daylight-saving change instead of drifting to 23:00 — the same reason
    `charts.py` walks whole local days. 06:00 is a time; 05:43 is not.
    """
    span_h = (end - start).total_seconds() / 3600
    step = _tick_step_hours(span_h)

    # Naive, so the stepping is on the clock rather than on the elapsed
    # second. The zone goes back on one reading at a time.
    naive = (
        start.astimezone(tz)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .replace(tzinfo=None)
    )

    found: list[Tick] = []
    previous: datetime | None = None
    while True:
        local = naive.replace(tzinfo=tz)
        moment = local.astimezone(UTC)
        if moment > end:
            break
        # The hour that does not exist on the spring-forward Sunday folds
        # onto its neighbour; one tick there, not two in the same place.
        if moment >= start and moment != previous:
            is_midnight = naive.hour == 0 and naive.minute == 0
            found.append(
                Tick(
                    at=moment,
                    x=x_for(moment),
                    label=naive.strftime("%H:%M"),
                    is_day_start=is_midnight,
                    # Not %-d: it is not portable, and charts.py already
                    # spells the day out this way for the same reason.
                    day_label=(
                        f"{naive:%a} {naive.day} {naive:%b}" if is_midnight else ""
                    ),
                )
            )
            previous = moment
        naive += timedelta(hours=step)
    return tuple(found)


def _curve_points(
    feed: FeedMark,
    *,
    start: datetime,
    end: datetime,
    x_for,
    baseline: float,
    height: float,
) -> list[tuple[float, float, Band]]:
    """Sample the rise curve, clipped to the window, with each point's band.

    Sampling rather than solving for the band boundaries: the curve is drawn
    at ten-minute resolution anyway, and a sampled boundary is at worst ten
    minutes out on a prediction that is hours wide.
    """
    if feed.peak_h <= 0:
        return []

    # The curve is over at twice the peak, where the parabola reaches zero.
    curve_end = feed.at + timedelta(hours=feed.peak_h * timing.PAST_TO)
    from_at = max(feed.at, start)
    to_at = min(curve_end, end)
    if to_at < from_at:
        return []

    step = timedelta(minutes=SAMPLE_MIN)
    count = max(int(math.ceil((to_at - from_at) / step)), 1)

    found: list[tuple[float, float, Band]] = []
    for index in range(count + 1):
        at = min(from_at + step * index, to_at)
        hours = (at - feed.at).total_seconds() / 3600
        ready = timing.readiness(hours, feed.peak_h)
        found.append(
            (x_for(at), baseline - ready.score * height, ready.band)
        )
        if at >= to_at:
            break
    return found


def _segment(
    points: Sequence[tuple[float, float, Band]]
) -> tuple[CurveSegment, ...]:
    """Cut a sampled curve into one polyline per band.

    Each segment repeats the point the next one starts at, so the pieces
    join up instead of showing a gap at every colour change.
    """
    if not points:
        return ()

    segments: list[CurveSegment] = []
    run: list[tuple[float, float]] = [(points[0][0], points[0][1])]
    band = points[0][2]

    for x, y, this_band in points[1:]:
        if this_band is not band:
            run.append((x, y))
            segments.append(CurveSegment(band=band, points=tuple(run)))
            run = [(x, y)]
            band = this_band
        else:
            run.append((x, y))
    segments.append(CurveSegment(band=band, points=tuple(run)))
    return tuple(segments)


def ribbon(
    series: Sequence[RibbonSeries],
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    tz: tzinfo,
    busy: Sequence[BusyMark] = (),
) -> Ribbon | None:
    """Lay out one row per jar against a shared time axis.

    None when there are no jars to draw; a jar with nothing logged still gets
    a row, because an empty row with "never fed" on it says something and a
    missing row says nothing.
    """
    if not series:
        return None

    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return None

    plot = PlotBox(
        x=MARGIN_X,
        y=HEADER_H,
        w=WIDTH - MARGIN_X * 2,
        h=ROW_H * len(series),
    )

    def x_for(at: datetime) -> float:
        # Clamped: a curve running off either end should stop at the edge
        # rather than being drawn outside the box.
        fraction = (at - start).total_seconds() / seconds
        return plot.x + min(max(fraction, 0.0), 1.0) * plot.w

    rows: list[RibbonRow] = []
    for slot, one in enumerate(series, start=1):
        top = plot.y + ROW_H * (slot - 1)
        label_y = top + ROW_LABEL_H - 3
        curve_top = top + ROW_LABEL_H
        baseline = curve_top + ROW_CURVE_H

        curves: list[RiseCurve] = []
        for feed in one.feeds:
            sampled = _curve_points(
                feed, start=start, end=end, x_for=x_for,
                baseline=baseline, height=ROW_CURVE_H,
            )
            peak_at = feed.at + timedelta(hours=feed.peak_h)
            curves.append(
                RiseCurve(
                    segments=_segment(sampled),
                    feed=feed,
                    x=x_for(feed.at),
                    peak_x=(
                        x_for(peak_at) if start <= peak_at <= end else None
                    ),
                    peak_at=peak_at,
                    baseline=baseline,
                )
            )

        # An observation sits at its measured rise, against the prediction:
        # 100% — a doubling — reads as the top of the band, so a jar that
        # beat the model is drawn above its own curve.
        observations = tuple(
            ObservationPoint(
                mark=mark,
                x=x_for(mark.at),
                y=baseline - min(max(mark.rise_pct / 100.0, 0.0), 1.2) * ROW_CURVE_H,
            )
            for mark in one.observations
            if start <= mark.at <= end
        )

        rows.append(
            RibbonRow(
                name=one.name,
                jar_id=one.jar_id,
                slot=slot,
                is_control=one.is_control,
                curves=tuple(curves),
                planned=tuple(
                    PlannedPoint(mark=mark, x=x_for(mark.at))
                    for mark in one.planned
                    if start <= mark.at <= end
                ),
                observations=observations,
                top=curve_top,
                bottom=baseline,
                label_y=label_y,
                note=one.note,
            )
        )

    shades = tuple(
        BusyShade(x1=x_for(mark.start), x2=x_for(mark.end), label=mark.label)
        for mark in busy
        if mark.end > start and mark.start < end
    )

    height = HEADER_H + ROW_H * len(series) + AXIS_H
    return Ribbon(
        rows=tuple(rows),
        ticks=_ticks(start, end, tz, x_for),
        busy=shades,
        start=start,
        end=end,
        now=now,
        now_x=x_for(now),
        plot=plot,
        viewbox=f"0 0 {WIDTH:g} {height:g}",
        axis_y=plot.bottom,
    )


def window(
    now: datetime, span_h: int, *, look_back_h: float = 6.0
) -> tuple[datetime, datetime]:
    """The stretch of time a ribbon shows.

    Weighted towards the future, because the ribbon is for deciding what to
    do next — but not entirely, or the rise now underway would be cut off at
    its most interesting point.
    """
    back = min(look_back_h, span_h / 3)
    return now - timedelta(hours=back), now + timedelta(hours=span_h - back)
