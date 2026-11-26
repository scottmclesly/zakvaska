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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, tzinfo

from app.services import timing
from app.services.charts import PlotBox
from app.services.timing import Band

# --- Geometry -----------------------------------------------------------
#
# One user unit is one CSS pixel, near enough: every picture is laid out at
# several widths and the page shows whichever is closest to the space it has
# (see `SIZES`), so nothing is ever stretched far. That is what lets the type
# be written at the size it should be read at, and lets a wider picture spend
# its width on time — more hours to the inch, more clock labels — instead of
# on bigger letters. The viewBox height is worked out from the number of rows.

#: The narrowest rendition, and the one every caller gets back directly.
WIDTH = 360.0
#: Every width a picture is drawn at, narrowest first. The stylesheet's
#: container queries choose between them (`.chart-fit` in app.css), so the
#: two lists have to agree.
SIZES = (360.0, 560.0, 820.0, 1180.0)
#: Left and right margins. Narrow: the ribbon wants its width for time.
MARGIN_X = 6.0
#: Above the first row, for the day labels.
HEADER_H = 18.0
#: One jar's row: a name line, then the band the curve is drawn in, then
#: room under the baseline for the feed's ratio.
ROW_LABEL_H = 20.0
ROW_CURVE_H = 44.0
ROW_GAP_H = 18.0
#: The strip under the last row that carries the clock times.
AXIS_H = 22.0

ROW_H = ROW_LABEL_H + ROW_CURVE_H + ROW_GAP_H

#: Head to head: every jar on the one baseline, so the curve band is taller —
#: the gap between two peaks is the thing being read — and there is no name
#: line, because the names are in the key above it.
DUEL_TOP_H = 8.0
DUEL_CURVE_H = 96.0

#: How often the curve is sampled. Fine enough that the peak reads as round.
SAMPLE_MIN = 10.0
#: At most this many clock labels across the narrowest picture, or they
#: collide. Wider ones get more in proportion: see `_max_ticks`.
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
class PreheatMark:
    """The oven coming up to temperature before the bake step.

    Not a step, which is exactly why it is handed over separately: it runs
    alongside the step before the bake rather than after it, so it cannot
    be a bar in the stack without claiming time of its own.
    """

    start: datetime
    end: datetime
    lead_min: int


@dataclass(frozen=True)
class RibbonSeries:
    """One jar's worth of ribbon."""

    name: str
    jar_id: int
    feeds: Sequence[FeedMark] = ()
    planned: Sequence[PlannedMark] = ()
    observations: Sequence[ObservationMark] = ()
    is_control: bool = False
    #: The jar's lid colour, as "#rrggbb", drawn as a dot by its name so a
    #: row can be matched to the jar on the shelf. None for a jar with no
    #: colour set, which is most of them.
    cap_color: str | None = None
    #: True while the jar's peak times are the model's guess about rye in
    #: general rather than a measurement of this jar. Drawn as one word by
    #: the row's label, because a curve that looks exact and is not is worse
    #: than no curve.
    is_estimate: bool = False
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
    cap_color: str | None = None
    is_estimate: bool = False
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
    #: How wide this one was drawn, in user units.
    width: float = WIDTH
    #: The same ribbon at every width in `SIZES`, this one included. Empty
    #: on the wider renditions themselves: only the one handed back carries
    #: the set.
    sizes: tuple["Ribbon", ...] = ()

    @property
    def span_h(self) -> float:
        return (self.end - self.start).total_seconds() / 3600

    @property
    def clashes(self) -> tuple[PlannedPoint, ...]:
        return tuple(one for row in self.rows for one in row.clashes)


# --- Laying it out ------------------------------------------------------


def _max_ticks(width: float) -> int:
    """A clock label needs about 45 units to itself, whatever the width."""
    return max(MAX_TICKS, int(width / 45))


def _tick_step_hours(span_h: float, max_ticks: int = MAX_TICKS) -> int:
    for hours in _TICK_HOURS:
        if span_h / hours <= max_ticks:
            return hours
    return _TICK_HOURS[-1]


def _ticks(
    start: datetime, end: datetime, tz: tzinfo, x_for,
    max_ticks: int = MAX_TICKS,
) -> tuple[Tick, ...]:
    """Clock-aligned ticks, so the labels are times a person recognises.

    Walked as local wall-clock hours from local midnight and only then
    converted, which is what keeps a midnight tick at midnight across a
    daylight-saving change instead of drifting to 23:00 — the same reason
    `charts.py` walks whole local days. 06:00 is a time; 05:43 is not.
    """
    span_h = (end - start).total_seconds() / 3600
    step = _tick_step_hours(span_h, max_ticks)

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

    What comes back is the narrowest drawing, which is the one everything
    that reads coordinates has always had. Its `sizes` holds the same ribbon
    at every width in `SIZES`, for the template to emit side by side.
    """
    drawn = tuple(
        _ribbon_at(
            width, series, start=start, end=end, now=now, tz=tz, busy=busy
        )
        for width in SIZES
    )
    if drawn[0] is None:
        return None
    return replace(drawn[0], sizes=drawn)


def head_to_head(
    series: Sequence[RibbonSeries],
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    tz: tzinfo,
    busy: Sequence[BusyMark] = (),
) -> Ribbon | None:
    """The same jars as `ribbon`, laid over one another on a single baseline.

    Stacked rows answer "what does each jar need, and when"; this answers the
    notebook's own question — which of two starters fed alike is the quicker
    and the stronger — and that is read off the distance between two curves,
    which only shows when they share an axis in both directions.
    """
    if len(series) < 2:
        return None
    drawn = tuple(
        _ribbon_at(
            width, series, start=start, end=end, now=now, tz=tz, busy=busy,
            overlay=True,
        )
        for width in SIZES
    )
    if drawn[0] is None:
        return None
    return replace(drawn[0], sizes=drawn)


def _ribbon_at(
    width: float,
    series: Sequence[RibbonSeries],
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    tz: tzinfo,
    busy: Sequence[BusyMark] = (),
    overlay: bool = False,
) -> Ribbon | None:
    if not series:
        return None
    label_h = DUEL_TOP_H if overlay else ROW_LABEL_H
    curve_h = DUEL_CURVE_H if overlay else ROW_CURVE_H
    row_h = label_h + curve_h + ROW_GAP_H

    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return None

    plot = PlotBox(
        x=MARGIN_X,
        y=HEADER_H,
        w=width - MARGIN_X * 2,
        h=row_h * (1 if overlay else len(series)),
    )

    def x_for(at: datetime) -> float:
        # Clamped: a curve running off either end should stop at the edge
        # rather than being drawn outside the box.
        fraction = (at - start).total_seconds() / seconds
        return plot.x + min(max(fraction, 0.0), 1.0) * plot.w

    rows: list[RibbonRow] = []
    for slot, one in enumerate(series, start=1):
        top = plot.y + (0 if overlay else row_h * (slot - 1))
        label_y = top + label_h - 6
        curve_top = top + label_h
        baseline = curve_top + curve_h

        curves: list[RiseCurve] = []
        for feed in one.feeds:
            sampled = _curve_points(
                feed, start=start, end=end, x_for=x_for,
                baseline=baseline, height=curve_h,
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
                y=baseline - min(max(mark.rise_pct / 100.0, 0.0), 1.2) * curve_h,
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
                cap_color=one.cap_color,
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
                is_estimate=one.is_estimate,
                note=one.note,
            )
        )

    shades = tuple(
        BusyShade(x1=x_for(mark.start), x2=x_for(mark.end), label=mark.label)
        for mark in busy
        if mark.end > start and mark.start < end
    )

    height = HEADER_H + plot.h + AXIS_H
    return Ribbon(
        rows=tuple(rows),
        ticks=_ticks(start, end, tz, x_for, _max_ticks(width)),
        busy=shades,
        start=start,
        end=end,
        now=now,
        now_x=x_for(now),
        plot=plot,
        viewbox=f"0 0 {width:g} {height:g}",
        axis_y=plot.bottom,
        width=width,
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


# --- A bake day laid out ------------------------------------------------
#
# Same visual language as the feeding ribbon — one time axis, busy blocks
# shaded behind, "now" over the top — but the rows are a bake's steps rather
# than a jar's cycles, and each one is a bar with a start and an end rather
# than a curve.


@dataclass(frozen=True)
class StepBar:
    """One step of a bake, as a bar on the timeline."""

    key: str
    name: str
    x1: float
    x2: float
    y: float
    height: float
    hands_on: bool
    must_be_home: bool
    clashes: bool
    #: Which lane it was put in, so overlapping labels can be staggered.
    lane: int
    start: datetime
    end: datetime
    conflict_label: str | None = None

    @property
    def width(self) -> float:
        return max(self.x2 - self.x1, 0.6)

    @property
    def mid(self) -> float:
        return (self.x1 + self.x2) / 2


@dataclass(frozen=True)
class PreheatBand:
    """Where the preheat is drawn: across the rows, not along one."""

    x1: float
    x2: float
    #: The top of the band, and how far down it reaches. It covers the bake
    #: bar and the row above it, because overlapping the end of that row —
    #: the final proof — is the thing worth seeing.
    y: float
    height: float
    start: datetime
    end: datetime
    lead_min: int

    @property
    def width(self) -> float:
        return max(self.x2 - self.x1, 0.6)


@dataclass(frozen=True)
class Timeline:
    bars: tuple[StepBar, ...]
    ticks: tuple[Tick, ...]
    busy: tuple[BusyShade, ...]
    start: datetime
    end: datetime
    now: datetime
    now_x: float | None
    plot: PlotBox
    viewbox: str
    axis_y: float
    #: Where the jar's readiness curve is drawn, when there is a jar.
    jar_curve: RiseCurve | None = None
    jar_name: str | None = None
    #: The levain build, marked on that curve.
    levain_x: float | None = None
    #: The oven coming up to temperature, where there is one to preheat.
    preheat: PreheatBand | None = None
    #: As on `Ribbon`: this drawing's width, and the whole set.
    width: float = WIDTH
    sizes: tuple["Timeline", ...] = ()

    @property
    def span_h(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


#: One bar per step, each its own row: a bake day is ten steps at most and
#: stacking them keeps every name readable without a tooltip.
BAR_H = 20.0
BAR_GAP = 4.0
#: The strip above the bars holding the jar's readiness curve.
JAR_BAND_H = 40.0


def timeline(
    steps: Sequence,
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    tz: tzinfo,
    busy: Sequence[BusyMark] = (),
    jar_feed: FeedMark | None = None,
    jar_name: str | None = None,
    levain_at: datetime | None = None,
    preheat: PreheatMark | None = None,
) -> Timeline | None:
    """Lay a bake's steps out along a time axis.

    `steps` are `services.bakeplan.Step`s. Taken as anything with the right
    attributes rather than imported, so this module still knows nothing about
    recipes or the ORM — it only draws.

    As with `ribbon`, the narrowest drawing comes back and carries the rest
    in `sizes`.
    """
    drawn = tuple(
        _timeline_at(
            width, steps, start=start, end=end, now=now, tz=tz, busy=busy,
            jar_feed=jar_feed, jar_name=jar_name, levain_at=levain_at,
            preheat=preheat,
        )
        for width in SIZES
    )
    if drawn[0] is None:
        return None
    return replace(drawn[0], sizes=drawn)


def _timeline_at(
    width: float,
    steps: Sequence,
    *,
    start: datetime,
    end: datetime,
    now: datetime,
    tz: tzinfo,
    busy: Sequence[BusyMark] = (),
    jar_feed: FeedMark | None = None,
    jar_name: str | None = None,
    levain_at: datetime | None = None,
    preheat: PreheatMark | None = None,
) -> Timeline | None:
    if not steps:
        return None
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return None

    jar_band = JAR_BAND_H if jar_feed is not None else 0.0
    plot = PlotBox(
        x=MARGIN_X,
        y=HEADER_H,
        w=width - MARGIN_X * 2,
        h=jar_band + len(steps) * (BAR_H + BAR_GAP),
    )

    def x_for(at: datetime) -> float:
        fraction = (at - start).total_seconds() / seconds
        return plot.x + min(max(fraction, 0.0), 1.0) * plot.w

    bars: list[StepBar] = []
    top = plot.y + jar_band
    for index, step in enumerate(steps):
        y = top + index * (BAR_H + BAR_GAP)
        bars.append(
            StepBar(
                key=step.key,
                name=step.name,
                x1=x_for(step.start),
                x2=x_for(step.end),
                y=y,
                height=BAR_H,
                hands_on=step.hands_on,
                must_be_home=step.must_be_home,
                clashes=step.clashes,
                lane=index,
                start=step.start,
                end=step.end,
                conflict_label=(
                    step.conflict.label if step.conflict is not None else None
                ),
            )
        )

    jar_curve = None
    if jar_feed is not None:
        baseline = plot.y + jar_band - 4
        sampled = _curve_points(
            jar_feed, start=start, end=end, x_for=x_for,
            baseline=baseline, height=jar_band - 8,
        )
        jar_curve = RiseCurve(
            segments=_segment(sampled),
            feed=jar_feed,
            x=x_for(jar_feed.at),
            peak_at=jar_feed.at + timedelta(hours=jar_feed.peak_h),
            peak_x=(
                x_for(jar_feed.at + timedelta(hours=jar_feed.peak_h))
                if start
                <= jar_feed.at + timedelta(hours=jar_feed.peak_h)
                <= end
                else None
            ),
            baseline=baseline,
        )

    band = None
    if preheat is not None and preheat.end > start and preheat.start < end:
        # Anchored to the bar it belongs to rather than to a row number, so
        # it stays on the bake wherever in the chain that lands. It reaches
        # one row up, over the end of whatever comes before — which is the
        # final proof, and the overlap is the point.
        baking = next((one for one in bars if one.key == "bake"), None)
        if baking is None:
            baking = bars[-1]
        top = max(baking.y - (BAR_H + BAR_GAP), plot.y + jar_band)
        band = PreheatBand(
            x1=x_for(preheat.start),
            x2=x_for(preheat.end),
            y=top,
            height=baking.y + BAR_H - top,
            start=preheat.start,
            end=preheat.end,
            lead_min=preheat.lead_min,
        )

    shades = tuple(
        BusyShade(x1=x_for(mark.start), x2=x_for(mark.end), label=mark.label)
        for mark in busy
        if mark.end > start and mark.start < end
    )

    height = HEADER_H + plot.h + AXIS_H
    return Timeline(
        bars=tuple(bars),
        ticks=_ticks(start, end, tz, x_for, _max_ticks(width)),
        busy=shades,
        start=start,
        end=end,
        now=now,
        now_x=x_for(now) if start <= now <= end else None,
        plot=plot,
        viewbox=f"0 0 {width:g} {height:g}",
        width=width,
        axis_y=plot.bottom,
        jar_curve=jar_curve,
        jar_name=jar_name,
        levain_x=(
            x_for(levain_at)
            if levain_at is not None and start <= levain_at <= end
            else None
        ),
        preheat=band,
    )


def timeline_window(
    plan_start: datetime, plan_end: datetime, now: datetime
) -> tuple[datetime, datetime]:
    """A little air either side of the plan, and `now` kept on the picture."""
    pad = max((plan_end - plan_start) * 0.04, timedelta(minutes=20))
    start = min(plan_start, now) - pad
    return start, plan_end + pad
