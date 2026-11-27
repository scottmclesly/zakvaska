"""A jar's feeding plan: what has happened, and what is meant to happen next.

The difference between this and `schedule.py` is intent. `schedule.py` asks
"when is this jar next due", which is a fact about the last feed and an
interval. This asks "when is the next feed *planned*", which is a thing Scott
can move — and moving it has to move every later feed with it, or a schedule
nudged an hour earlier on Tuesday drifts back by Thursday.

That is what the anchor is for. `jar.schedule_anchor_utc` is one planned feed
time; every other planned feed is a whole number of cycles away from it. So
moving a feed writes a new anchor and the chain stays aligned, and a feed
logged late can either keep the old anchor (the app suggests a ratio that
puts the peak back where it belongs) or set a new one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import JarState
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.services import busy as busy_service
from app.services import learning, ribbon
from app.services import settings_store, timing
from app.services.busy import BusyInterval
from app.services.schedule import last_feeding
from app.services.timing import Band, Readiness

#: How far from a planned feed still counts as having kept to it. Beyond
#: this, the feed confirmation offers to shift the schedule instead.
LATE_GRACE_H = 1.0

#: The nudge buttons beside a planned feed, in minutes. Dragging a marker on
#: a phone is fiddly and needs JavaScript; four buttons and a time picker do
#: the same job with neither.
NUDGES = (-60, -30, 30, 60)


def nudge_label(minutes: int) -> str:
    """"−1 h", "+30 m" — with a real minus sign, not a hyphen."""
    sign = "−" if minutes < 0 else "+"
    size = abs(minutes)
    return f"{sign}{size // 60} h" if size >= 60 else f"{sign}{size} m"


@dataclass(frozen=True)
class FedCycle:
    """One feed, and the rise it set off."""

    fed_at: datetime
    #: Flour ÷ starter. None for a build with no starter carried over.
    ratio: float | None
    temp_c: float
    #: Hours from the feed to its predicted peak.
    peak_h: float
    #: True when the temperature was assumed rather than logged.
    temp_assumed: bool
    feeding: Feeding | None = None

    @property
    def peak_at(self) -> datetime:
        return self.fed_at + timedelta(hours=self.peak_h)

    def readiness_at(self, moment: datetime) -> Readiness:
        hours = (moment - self.fed_at).total_seconds() / 3600
        return timing.readiness(hours, self.peak_h)

    @property
    def ratio_label(self) -> str | None:
        return None if self.ratio is None else timing.ratio_label(self.ratio)


@dataclass(frozen=True)
class PlannedFeed:
    """A feed that has not happened yet."""

    at: datetime
    #: 1 for the next one, 2 for the one after, and so on.
    index: int

    @property
    def is_next(self) -> bool:
        return self.index == 1


@dataclass(frozen=True)
class JarPlan:
    """Everything the ribbon and the alerts need to know about one jar."""

    jar: Jar
    cycle_h: float
    last_cycle: FedCycle | None
    planned: tuple[PlannedFeed, ...]
    #: True when the plan follows a moved anchor rather than the last feed.
    anchored: bool
    #: This jar's measured correction to the model, worked out once and
    #: carried, because every prediction on the page needs it and looking it
    #: up per feed would be a query per curve on the ribbon.
    factor: float = 1.0
    #: How many recorded peaks that correction rests on.
    peaks_recorded: int = 0

    @property
    def is_estimate(self) -> bool:
        """Whether the peak times here are worth calling predictions.

        Below a few recorded peaks they are the model's guess about rye in
        general, not about this jar, and saying so costs one word.
        """
        return self.peaks_recorded < learning.CONFIDENT_AT

    @property
    def next_feed_at(self) -> datetime | None:
        return self.planned[0].at if self.planned else None

    @property
    def has_plan(self) -> bool:
        """Whether there is a planned feed to prefer over the fixed interval."""
        return bool(self.planned)

    def readiness_at(self, moment: datetime) -> Readiness | None:
        if self.last_cycle is None:
            return None
        return self.last_cycle.readiness_at(moment)

    def suggested_ratio(self, from_moment: datetime, temp_c: float | None = None) -> float | None:
        """What to feed it now so the peak lands on the next planned feed.

        None when there is nothing planned to aim at. This is the advice on
        the Fed-it form: the whole point of knowing the cycle is controllable.
        """
        target = self.next_feed_at
        if target is None:
            return None
        hours = (target - from_moment).total_seconds() / 3600
        if hours <= 0:
            return None
        at_temp = temp_c if temp_c is not None else (
            self.last_cycle.temp_c if self.last_cycle else timing.REF_TEMP_C
        )
        return timing.solve_ratio(hours, at_temp, self.factor)


# --- Pieces ------------------------------------------------------------


def jar_factor(session: Session, jar: Jar) -> float:
    """This jar's measured correction to the model.

    One function every prediction goes through, so a jar that has been
    watched a few times corrects the ribbon, the planner and the ratio
    advice all at once. `services.learning` is where the arithmetic lives;
    this is only the door into it.
    """
    return learning.factor(session, jar)


def cycle_hours(session: Session, jar: Jar) -> float:
    """How long this jar's feeding cycle is.

    Feeds a day is what drives the plan for a jar on the counter. A jar in
    the fridge keeps its own interval, because "twice a day" is not what is
    happening to it at all — it is being fed weekly.
    """
    if jar.state is JarState.FRIDGE:
        return float(jar.feed_interval_fridge_h)
    return timing.cycle_hours(settings_store.jar_feeds_per_day(session, jar))


def cycle_for_feeding(
    session: Session,
    feeding: Feeding,
    jar: Jar,
    *,
    default_temp_c: float | None = None,
    factor: float | None = None,
) -> FedCycle:
    """Work out the rise one logged feeding set off.

    `factor` is this jar's measured correction. Callers drawing a whole
    ribbon pass the one they already have: it is the same for every feed of
    the same jar, and looking it up per curve would be a query a curve.
    """
    fallback = (
        default_temp_c
        if default_temp_c is not None
        else settings_store.default_ferment_temp_c(session)
    )
    temp_c = feeding.ambient_temp_c
    assumed = temp_c is None
    if temp_c is None:
        temp_c = fallback

    ratio = timing.feed_ratio(feeding.starter_g, feeding.flour_g)
    # A build with no starter has no ratio; treat it as a 1:1:1 for timing,
    # which is the fastest the model goes, rather than refusing to draw it.
    peak_h = timing.predict_peak_h(
        ratio if ratio is not None else 1.0,
        temp_c,
        factor if factor is not None else jar_factor(session, jar),
    )
    return FedCycle(
        fed_at=feeding.fed_at,
        ratio=ratio,
        temp_c=temp_c,
        peak_h=peak_h,
        temp_assumed=assumed,
        feeding=feeding,
    )


def cycles_on(
    moment: datetime, cycle: timedelta, steps: int = 1, *, tz: tzinfo | None = None
) -> datetime:
    """`moment` plus whole cycles, **counted on the kitchen clock**.

    A feeding rhythm is a pattern on the wall clock, the same as a busy block
    is (services/busy.py): eight and eight means eight and eight, including
    the week the clocks change. Adding twelve real hours to an instant would
    move every later feed to seven and seven after the autumn change and
    leave it there until somebody noticed.

    So the arithmetic is done on the naive local reading and the zone is put
    back afterwards. The night of a change is then an hour short or long in
    real time, which is true, and which the rise curve — real elapsed hours,
    always — shows honestly beside it. A slot that lands in the hour that
    does not exist is rung at the instant the old clock would have reached
    it; one that lands in the hour that comes twice is rung the first time.
    """
    if steps == 0:
        return moment
    zone = tz or get_settings().tz
    naive = moment.astimezone(zone).replace(tzinfo=None)
    return (naive + cycle * steps).replace(tzinfo=zone, fold=0).astimezone(UTC)


def _steps_from_anchor(anchor: datetime, cycle: timedelta, after: datetime) -> int:
    """How many whole cycles on from the anchor the first feed at or after
    `after` is.

    Counted in whole cycles from the anchor, so every planned feed stays on
    the same grid however long ago the anchor was set. The walk only ever
    goes forward: an anchor is the earliest feed it plans, never a phase to
    be stepped back through. Otherwise moving tonight's feed to 22:15 would
    answer "next feed at 10:15 this morning", which is a grid-aligned time
    and completely the wrong answer to what was asked.
    """
    if cycle <= timedelta(0):
        return 0
    # A first guess in real hours, then put right on the clock: across a
    # clock change the two can disagree by one slot.
    steps = max(math.ceil((after - anchor) / cycle - 1e-9), 0)
    while steps > 0 and cycles_on(anchor, cycle, steps - 1) >= after:
        steps -= 1
    while cycles_on(anchor, cycle, steps) < after:
        steps += 1
    return steps


def _next_planned_from_anchor(
    anchor: datetime, cycle: timedelta, after: datetime
) -> datetime:
    """The first anchor-aligned feed at or after `after`."""
    return cycles_on(anchor, cycle, _steps_from_anchor(anchor, cycle, after))


def planned_feeds(
    session: Session,
    jar: Jar,
    *,
    now: datetime,
    until: datetime,
    last_fed_at: datetime | None = None,
) -> tuple[tuple[PlannedFeed, ...], bool]:
    """Every planned feed from `now` to `until`, and whether it is anchored.

    Never empty for a jar with a plan: when the next feed lies past `until`
    it is returned alone, so "what is next" always has an answer.

    A jar that sleeps has no plan, and nor does one that has never been fed
    and has no anchor: there is nothing to count cycles from.
    """
    if not jar.state.wants_feeding:
        return (), False

    cycle = timedelta(hours=cycle_hours(session, jar))
    if cycle <= timedelta(0):
        return (), False
    anchor = jar.schedule_anchor_utc
    anchored = anchor is not None

    if anchor is None:
        if last_fed_at is None:
            return (), False
        anchor = cycles_on(last_fed_at, cycle)

    def slot(n: int) -> datetime:
        return cycles_on(anchor, cycle, n)

    # The first feed still owed: the earliest slot on the grid after the
    # last actual feed. It may well be in the past, and when it is, that is
    # precisely the overdue feed the app should be asking about — rolling
    # forward to the next future slot would mean a jar fed twenty hours ago
    # on a twelve-hour cycle was never reported as due at all.
    if last_fed_at is None:
        first = 0
    else:
        first = _steps_from_anchor(anchor, cycle, last_fed_at)
        if slot(first) <= last_fed_at:
            first += 1

    feeds: list[PlannedFeed] = []
    index = 1
    if slot(first) <= now:
        # One missed feed is worth naming; a week of them is just history,
        # so the rest of the list picks up from the present.
        feeds.append(PlannedFeed(at=slot(first), index=index))
        index += 1
        n = max(_steps_from_anchor(anchor, cycle, now), first + 1)
    else:
        n = first

    # The bound keeps a short cycle from filling the page; a 24 h ribbon at a
    # 12 h cycle wants two, and nothing sane wants more than this.
    while slot(n) <= until and index <= 64:
        feeds.append(PlannedFeed(at=slot(n), index=index))
        n += 1
        index += 1
    # The next feed is always worth knowing, however far off it is. `until`
    # is how far a ribbon can draw, not how far a plan can reach: a feed
    # moved to the day after tomorrow, or a weekly one in the fridge, lies
    # past the edge of a 48-hour ribbon and is still the next feed. Without
    # this the jar's page said "nothing planned yet" about a feed it had
    # just been told to plan, and offered no way to take the move back. The
    # ribbon only draws what falls inside its window, so one feed beyond it
    # costs the drawing nothing.
    if not feeds:
        feeds.append(PlannedFeed(at=slot(n), index=index))
    return tuple(feeds), anchored


def jar_plan(
    session: Session, jar: Jar, *, now: datetime, until: datetime
) -> JarPlan:
    previous = last_feeding(session, jar.id)
    cycle_h = cycle_hours(session, jar)
    # One read of the jar's recorded peaks, for both the correction and how
    # much of a correction it really is.
    learned = learning.learned(session, jar)
    factor = learned.factor
    feeds, anchored = planned_feeds(
        session, jar, now=now, until=until,
        last_fed_at=previous.fed_at if previous else None,
    )
    return JarPlan(
        jar=jar,
        cycle_h=cycle_h,
        last_cycle=(
            cycle_for_feeding(session, previous, jar, factor=factor)
            if previous
            else None
        ),
        planned=feeds,
        anchored=anchored,
        factor=factor,
        peaks_recorded=learned.count,
    )


def recent_cycles(
    session: Session,
    jar: Jar,
    *,
    since: datetime,
    until: datetime,
    factor: float | None = None,
) -> list[FedCycle]:
    """The feeds whose rise curves fall inside a window, oldest first.

    One feed before the window is included on purpose: its curve is still
    being drawn when the window opens, and a ribbon that started with a bare
    axis would hide the rise Scott is actually looking at.
    """
    rows = list(
        session.scalars(
            select(Feeding)
            .where(Feeding.jar_id == jar.id, Feeding.fed_at <= until)
            .order_by(Feeding.fed_at.desc(), Feeding.id.desc())
            .limit(64)
        )
    )
    rows.reverse()

    default_temp = settings_store.default_ferment_temp_c(session)
    held = factor if factor is not None else jar_factor(session, jar)
    cycles = [
        cycle_for_feeding(
            session, row, jar, default_temp_c=default_temp, factor=held
        )
        for row in rows
    ]

    kept: list[FedCycle] = []
    for index, cycle in enumerate(cycles):
        # Its curve runs out at twice the peak, where the parabola hits zero
        # — or at the next feed, which ends the cycle whatever the parabola
        # says. A cycle cut off before the window opened has nothing left to
        # draw inside it.
        ends = cycle.fed_at + timedelta(hours=cycle.peak_h * timing.PAST_TO)
        if index + 1 < len(cycles):
            ends = min(ends, cycles[index + 1].fed_at)
        if ends >= since or cycle.fed_at >= since:
            kept.append(cycle)
    if not kept and cycles:
        kept = cycles[-1:]
    return kept


# --- Moving a feed ------------------------------------------------------


def move_next_feed(
    session: Session, jar: Jar, *, to: datetime, now: datetime
) -> datetime:
    """Put the next planned feed at `to`; every later one follows.

    Writing the anchor is the whole mechanism: later feeds are counted from
    it, so they move by exactly the same offset without being stored.
    """
    jar.schedule_anchor_utc = to
    session.flush()
    return to


def shift_next_feed(
    session: Session, jar: Jar, *, by: timedelta, now: datetime, until: datetime
) -> datetime | None:
    """Nudge the next planned feed by an offset. None if there is no plan."""
    plan = jar_plan(session, jar, now=now, until=until)
    target = plan.next_feed_at
    if target is None:
        return None
    return move_next_feed(session, jar, to=target + by, now=now)


def clear_anchor(session: Session, jar: Jar) -> None:
    """Go back to planning from the last feed."""
    jar.schedule_anchor_utc = None
    session.flush()


# --- A feed logged late -------------------------------------------------


@dataclass(frozen=True)
class LateFeed:
    """How far off the plan a feed landed, and what to offer about it."""

    planned_at: datetime
    fed_at: datetime

    @property
    def late_by(self) -> timedelta:
        return self.fed_at - self.planned_at

    @property
    def hours_late(self) -> float:
        return self.late_by.total_seconds() / 3600

    @property
    def is_late(self) -> bool:
        return self.hours_late > LATE_GRACE_H

    @property
    def is_early(self) -> bool:
        return self.hours_late < -LATE_GRACE_H

    @property
    def is_off_plan(self) -> bool:
        return self.is_late or self.is_early


def feed_against_plan(
    session: Session, jar: Jar, *, fed_at: datetime, now: datetime
) -> LateFeed | None:
    """Compare a feed about to be logged with the feed that was planned.

    None when there was no plan to be off, which is the case for a jar's
    first ever feed.
    """
    if last_feeding(session, jar.id) is None and jar.schedule_anchor_utc is None:
        return None

    # The feed this one is answering is the one the plan is already owed —
    # the same moment the ribbon draws and the alert fires on. Asking the
    # plan rather than rounding to the nearest slot is what keeps the three
    # of them agreeing: rounding would have the form call a feed "eight
    # hours late" for a slot the panel had already moved past.
    made = jar_plan(session, jar, now=fed_at, until=fed_at + timedelta(days=14))
    planned = made.next_feed_at
    if planned is None:
        return None
    return LateFeed(planned_at=planned, fed_at=fed_at)


def keep_usual_times(
    session: Session, jar: Jar, *, late: LateFeed
) -> datetime:
    """Leave the schedule where it is after a late feed.

    The anchor is written explicitly rather than left null: without it the
    plan would be recomputed from the feed that just happened, which is the
    drift this is here to prevent.
    """
    cycle = timedelta(hours=cycle_hours(session, jar))
    jar.schedule_anchor_utc = cycles_on(late.planned_at, cycle)
    session.flush()
    return jar.schedule_anchor_utc


def shift_schedule(session: Session, jar: Jar, *, late: LateFeed) -> datetime:
    """Move the whole schedule to suit the time the feed actually happened."""
    cycle = timedelta(hours=cycle_hours(session, jar))
    jar.schedule_anchor_utc = cycles_on(late.fed_at, cycle)
    session.flush()
    return jar.schedule_anchor_utc


# --- Advice ------------------------------------------------------------


@dataclass(frozen=True)
class RatioAdvice:
    """What to feed a jar now so its peak lands where it is wanted."""

    ratio: float
    temp_c: float
    target_at: datetime
    hours: float
    clamped_note: str | None = None

    @property
    def label(self) -> str:
        return timing.ratio_label(self.ratio)


def peak_target_from(plan_for: JarPlan) -> datetime | None:
    """The planned feed that a feed being logged should peak *at*.

    Not the next planned feed: that is the feed being logged. A starter wants
    to be at its peak when it is next fed — that is what the peak band means
    — so the feed going in now is aimed at the slot *after* the one it fills.
    Aiming it at its own slot asks for a peak an hour away, which no feedable
    ratio reaches, and the advice comes out as a caveat instead of a ratio.

    `plan_for` must be the plan as it stands at the moment of the feed, so
    that the slot being filled is the one `feed_against_plan` judged the feed
    against. The two readings of "which feed is this" have to be the same or
    the form contradicts itself.
    """
    answering = plan_for.next_feed_at
    if answering is None:
        return None
    return next((one.at for one in plan_for.planned if one.at > answering), None)


def peak_target(
    session: Session, jar: Jar, *, fed_at: datetime
) -> datetime | None:
    """`peak_target_from` for callers that have a jar rather than a plan."""
    return peak_target_from(
        jar_plan(session, jar, now=fed_at, until=fed_at + timedelta(days=14))
    )


def ratio_advice(
    *,
    from_moment: datetime,
    target_at: datetime,
    temp_c: float,
    factor: float = 1.0,
) -> RatioAdvice | None:
    """Advice, or None when the target is already behind us."""
    hours = (target_at - from_moment).total_seconds() / 3600
    if hours <= 0:
        return None
    ratio = timing.solve_ratio(hours, temp_c, factor)
    held = timing.clamp_inputs(ratio, temp_c)
    reached = timing.predict_peak_h(ratio, temp_c, factor)
    note = held.note
    # Say so when the best available ratio still misses by more than the
    # model's own accuracy; silently handing back the nearest is worse.
    if abs(reached - hours) > 1.0:
        note = (
            "The closest a feedable ratio gets is a peak about "
            f"{timing.hours_label(reached)} away, not "
            f"{timing.hours_label(hours)}."
        )
    return RatioAdvice(
        ratio=ratio,
        temp_c=temp_c,
        target_at=target_at,
        hours=hours,
        clamped_note=note,
    )


def band_of(plan: JarPlan, now: datetime) -> Band | None:
    ready = plan.readiness_at(now)
    return None if ready is None else ready.band


# --- Building a ribbon --------------------------------------------------
#
# The ribbon module knows nothing about the ORM, so this is where a jar and
# its rows turn into the plain marks it lays out.


def _observation_marks(
    session: Session, jar: Jar, *, since: datetime, until: datetime
) -> list[ribbon.ObservationMark]:
    from app.models.observation import Observation
    from app.services import derived

    marks: list[ribbon.ObservationMark] = []
    for row in session.scalars(
        select(Observation)
        .where(
            Observation.jar_id == jar.id,
            Observation.observed_at >= since,
            Observation.observed_at <= until,
        )
        .order_by(Observation.observed_at)
    ):
        value = derived.rise_pct(row.start_height_mm, row.height_mm)
        if value is not None:
            marks.append(
                ribbon.ObservationMark(at=row.observed_at, rise_pct=value)
            )
    return marks


def planned_marks(
    session: Session,
    jar: Jar,
    plan_for: JarPlan,
    *,
    now: datetime,
    busy: Sequence[BusyInterval] = (),
) -> list[ribbon.PlannedMark]:
    """Planned feeds, each told whether it lands in a busy block.

    A feed that clashes carries the time it could move to and the ratio that
    would put its peak there, so the badge on the ribbon can offer the fix
    rather than only naming the problem.
    """
    factor = plan_for.factor
    temp_c = (
        plan_for.last_cycle.temp_c
        if plan_for.last_cycle
        else settings_store.default_ferment_temp_c(session)
    )

    marks: list[ribbon.PlannedMark] = []
    for feed in plan_for.planned:
        clash = busy_service.covering(list(busy), feed.at)
        move_to = None
        move_ratio = None
        if clash is not None:
            move_to = busy_service.next_free(list(busy), feed.at)
            if move_to is not None:
                advice = ratio_advice(
                    from_moment=now, target_at=move_to,
                    temp_c=temp_c, factor=factor,
                )
                # Only when a feedable ratio actually reaches. A badge has no
                # room for the caveat, and "feed 1:10:10" next to a time the
                # peak cannot reach is worse than no ratio at all — the
                # panel below has the space to explain, so it does it there.
                if advice is not None and advice.clamped_note is None:
                    move_ratio = advice.label
        marks.append(
            ribbon.PlannedMark(
                at=feed.at,
                index=feed.index,
                busy_label=clash.label if clash else None,
                move_to=move_to,
                move_ratio_label=move_ratio,
            )
        )
    return marks


def jar_series(
    session: Session,
    jar: Jar,
    *,
    now: datetime,
    start: datetime,
    end: datetime,
    busy: Sequence[BusyInterval] = (),
) -> tuple[ribbon.RibbonSeries, JarPlan]:
    """One jar turned into the marks the ribbon lays out, and its plan."""
    made = jar_plan(session, jar, now=now, until=end)
    cycles = recent_cycles(
        session, jar, since=start, until=end, factor=made.factor
    )

    note = None
    if not cycles:
        note = "Never fed"
    elif not made.has_plan:
        note = f"No feeds planned — {jar.state.label.lower()}"

    series = ribbon.RibbonSeries(
        name=jar.name,
        jar_id=jar.id,
        feeds=tuple(
            ribbon.FeedMark(
                at=cycle.fed_at,
                peak_h=cycle.peak_h,
                ratio_label=cycle.ratio_label,
                temp_assumed=cycle.temp_assumed,
                # The feed that ended it, where there was one: the curve
                # stops there and hands over to the next one.
                ends_at=(
                    cycles[index + 1].fed_at
                    if index + 1 < len(cycles)
                    else None
                ),
            )
            for index, cycle in enumerate(cycles)
        ),
        projected=tuple(_projected_marks(cycles, made, now=now)),
        planned=tuple(planned_marks(session, jar, made, now=now, busy=busy)),
        observations=tuple(
            _observation_marks(session, jar, since=start, until=end)
        ),
        is_control=jar.is_control,
        cap_color=jar.cap_color,
        is_estimate=bool(cycles) and made.is_estimate,
        note=note,
    )
    return series, made


def _projected_marks(
    cycles: Sequence[FedCycle], made: JarPlan, *, now: datetime
) -> list[ribbon.FeedMark]:
    """The rise each planned feed would set off, if the plan is kept.

    A ribbon that stops at the next feed shows half a day of a two-day
    window. What comes after is not known, but it is not a mystery either:
    the same jar, fed the same way on the same rhythm, does the same thing.
    So each planned feed still ahead gets the last real feed's curve (its
    ratio, its temperature, this jar's own pace), running until the feed
    after it.

    Only feeds still to come: a planned feed already missed set nothing
    off, and drawing a rise from it would be drawing something that did
    not happen. And only with a real feed to copy.
    """
    if not cycles:
        return []
    last = cycles[-1]
    ahead = [feed for feed in made.planned if feed.at >= now]
    return [
        ribbon.FeedMark(
            at=feed.at,
            peak_h=last.peak_h,
            ratio_label=last.ratio_label,
            temp_assumed=last.temp_assumed,
            ends_at=ahead[index + 1].at if index + 1 < len(ahead) else None,
        )
        for index, feed in enumerate(ahead)
    ]


def build_ribbon(
    session: Session,
    jars: Sequence[Jar],
    *,
    now: datetime,
    tz,
    span_h: int | None = None,
):
    """A laid-out ribbon for these jars, and each jar's plan beside it.

    Returns (ribbon, {jar_id: JarPlan}). The plans come back too because the
    page wants them for the badges and the move buttons, and working them out
    twice would mean two different answers the moment a clock ticked.
    """
    span = span_h if span_h is not None else settings_store.ribbon_span_h(session)
    start, end = ribbon.window(now, span)
    intervals = busy_service.busy_intervals(session, start, end, tz)

    series: list[ribbon.RibbonSeries] = []
    plans: dict[int, JarPlan] = {}
    for jar in jars:
        one, made = jar_series(
            session, jar, now=now, start=start, end=end, busy=intervals
        )
        series.append(one)
        plans[jar.id] = made

    drawn = ribbon.ribbon(
        series,
        start=start,
        end=end,
        now=now,
        tz=tz,
        busy=tuple(
            ribbon.BusyMark(start=one.start, end=one.end, label=one.label)
            for one in intervals
        ),
    )
    return drawn, plans


def rivals(jars: Sequence[Jar]) -> list[Jar]:
    """The jars worth setting against each other, or none.

    The notebook exists to run starters side by side on the same flour — a
    homemade one against a bought control. So: the largest group of jars
    being fed that share a flour, when there are at least two of them. Jars
    on different flours are not a fair race and are left to the ribbon.
    """
    groups: dict[str, list[Jar]] = {}
    for jar in jars:
        flour = (jar.flour_type or "").strip().lower()
        if flour and jar.state.wants_feeding and not jar.archived:
            groups.setdefault(flour, []).append(jar)
    best = max(groups.values(), key=len, default=[])
    return best if len(best) >= 2 else []


def build_head_to_head(
    session: Session,
    jars: Sequence[Jar],
    *,
    now: datetime,
    tz,
    span_h: int | None = None,
):
    """`ribbon.head_to_head` for these jars, over the ribbon's own window.

    None unless there are two or more. Drawing only: it reads the same
    series the ribbon does and decides nothing.
    """
    if len(jars) < 2:
        return None
    span = span_h if span_h is not None else settings_store.ribbon_span_h(session)
    start, end = ribbon.window(now, span)
    intervals = busy_service.busy_intervals(session, start, end, tz)
    series = [
        jar_series(session, jar, now=now, start=start, end=end, busy=intervals)[0]
        for jar in jars
    ]
    return ribbon.head_to_head(
        series,
        start=start,
        end=end,
        now=now,
        tz=tz,
        busy=tuple(
            ribbon.BusyMark(start=one.start, end=one.end, label=one.label)
            for one in intervals
        ),
    )


# --- Trying a feed on before you log it ---------------------------------
#
# The reason `timing` exists at all is that the cycle length is controllable:
# more flour per gram of starter and the peak moves later. That is hard to
# believe from a sentence and obvious from a picture, so the Fed-it form
# draws the feed being typed — the rise it would set off, and the feed
# already planned sitting there as the thing to land on. Change the amounts
# and the peak slides; the planned feed does not, because it is the target.

#: The spans a preview frames itself at. A ladder rather than a snug fit, so
#: that nudging a ratio slides the peak along a steady axis instead of
#: rescaling the picture underneath it on every keystroke. It runs out to
#: several days because a thick feed in a cool room genuinely takes that
#: long to come back down, and the rungs are never a ceiling: see
#: `_preview_span_h`.
PREVIEW_SPANS_H = (8, 12, 18, 24, 36, 48, 72, 96, 120)

#: How close to the planned feed counts as landing on it, as a fraction of
#: the cycle. Taken from the peak band rather than picked: inside this the
#: jar is still at its peak when the feed is due, which is as fine a target
#: as the model can honestly mean.
PREVIEW_TOLERANCE = timing.PEAK_TO - 1.0


def _preview_span_h(needed_h: float) -> int:
    """The rung of the ladder that holds `needed_h`.

    Past the last rung it keeps going in whole days rather than settling for
    the longest one: a span that stopped there would start cutting the
    picture off again, which is the one thing the window may not do.
    """
    for span in PREVIEW_SPANS_H:
        if needed_h <= span:
            return span
    return int(math.ceil(needed_h / 24.0) * 24)


@dataclass(frozen=True)
class FeedPreview:
    """The feed being typed into the form, worked out before it exists."""

    jar: Jar
    fed_at: datetime
    temp_c: float
    #: True when no room temperature was typed and one had to be assumed.
    temp_assumed: bool
    #: Flour ÷ starter. None for a build with no starter carried over, which
    #: has no ratio to take and so no peak to predict.
    ratio: float | None
    peak_h: float | None
    peak_at: datetime | None
    #: The next planned feed after this one: what the peak is aimed at.
    target_at: datetime | None
    #: The busy block the peak lands in, if it lands in one.
    busy_label: str | None
    clamped_note: str | None
    #: What to feed instead so the peak lands on `target_at`.
    advice: RatioAdvice | None
    drawn: ribbon.Ribbon | None

    @property
    def has_ratio(self) -> bool:
        return self.ratio is not None

    @property
    def ratio_label(self) -> str | None:
        return None if self.ratio is None else timing.ratio_label(self.ratio)

    @property
    def gap_h(self) -> float | None:
        """Planned feed to peak, in hours. Negative means the peak is early."""
        if self.peak_at is None or self.target_at is None:
            return None
        return (self.peak_at - self.target_at).total_seconds() / 3600

    @property
    def tolerance_h(self) -> float | None:
        return None if self.peak_h is None else PREVIEW_TOLERANCE * self.peak_h

    @property
    def lands_well(self) -> bool:
        """Whether the jar would still be at its peak when the feed is due."""
        gap, tolerance = self.gap_h, self.tolerance_h
        if gap is None or tolerance is None:
            return False
        return abs(gap) <= tolerance

    @property
    def is_late(self) -> bool:
        gap = self.gap_h
        return not self.lands_well and gap is not None and gap > 0

    @property
    def is_early(self) -> bool:
        gap = self.gap_h
        return not self.lands_well and gap is not None and gap < 0

    @property
    def better_ratio_label(self) -> str | None:
        """A ratio that would land it closer, when a different one would.

        None when this feed already lands well, when the advice is the ratio
        already typed, and when no feedable ratio reaches the target — the
        advice card above the form has the room to explain that case, and a
        bare "feed 1:10:10" under the chart would only mislead.
        """
        if self.lands_well or self.advice is None:
            return None
        if self.advice.clamped_note is not None:
            return None
        if (
            self.ratio is not None
            and abs(self.advice.ratio - self.ratio) < timing.RATIO_STEP / 2
        ):
            return None
        return self.advice.label


def feed_preview(
    session: Session,
    jar: Jar,
    *,
    starter_g: float | None,
    flour_g: float | None,
    fed_at: datetime,
    now: datetime,
    tz,
    ambient_temp_c: float | None = None,
) -> FeedPreview:
    """Draw the feed being typed, against the feed already planned.

    Takes grams and a temperature rather than form strings: the route reads
    the form leniently, because this runs on every keystroke and a half-typed
    number should leave a picture standing rather than raise.
    """
    # As of the feed, not as of now: which planned slot this feed fills is
    # the same question `feed_against_plan` answers, and the form would
    # contradict itself if the two were worked out from different moments.
    made = jar_plan(session, jar, now=fed_at, until=fed_at + timedelta(days=14))

    temp_assumed = ambient_temp_c is None
    temp_c = ambient_temp_c
    if temp_c is None:
        temp_c = (
            made.last_cycle.temp_c
            if made.last_cycle
            else settings_store.default_ferment_temp_c(session)
        )

    ratio = timing.feed_ratio(starter_g, flour_g)
    peak_h = peak_at = clamped_note = None
    if ratio is not None:
        peak_h = timing.predict_peak_h(ratio, temp_c, made.factor)
        peak_at = fed_at + timedelta(hours=peak_h)
        clamped_note = timing.clamp_inputs(ratio, temp_c).note

    target_at = peak_target_from(made)
    advice = None
    if target_at is not None:
        advice = ratio_advice(
            from_moment=fed_at,
            target_at=target_at,
            temp_c=temp_c,
            factor=made.factor,
        )

    # What the window has to hold, whatever the amounts are swung to: the
    # curve all the way back down to the baseline, and the feeds planned
    # around it. Framing it on the peak alone cut the fall off at the right
    # edge, and the fall is half of what the picture is for — it is where
    # "feed it again by then" is read off.
    curve_end = (
        fed_at + timedelta(hours=peak_h * timing.PAST_TO)
        if peak_h is not None
        else None
    )
    # The slot this feed fills, as well as the one it is aimed at: both are
    # drawn, so both have to fit.
    next_planned = next((one.at for one in made.planned if one.at > fed_at), None)

    start = min(fed_at, now) - timedelta(hours=1)
    furthest = max(
        one
        for one in (fed_at, now, peak_at, curve_end, target_at, next_planned)
        if one is not None
    )
    span = _preview_span_h((furthest - start).total_seconds() / 3600 + 1.0)
    end = start + timedelta(hours=span)

    intervals = busy_service.busy_intervals(session, start, end, tz)
    feeds: tuple[ribbon.FeedMark, ...] = ()
    if ratio is not None and peak_h is not None:
        feeds = (
            ribbon.FeedMark(
                at=fed_at,
                peak_h=peak_h,
                ratio_label=timing.ratio_label(ratio),
                temp_assumed=temp_assumed,
            ),
        )

    series = ribbon.RibbonSeries(
        name=jar.name,
        jar_id=jar.id,
        feeds=feeds,
        planned=tuple(
            one
            for one in planned_marks(session, jar, made, now=now, busy=intervals)
            if one.at > fed_at and start <= one.at <= end
        ),
        is_control=jar.is_control,
        cap_color=jar.cap_color,
        is_estimate=ratio is not None and made.is_estimate,
        note=None if ratio is not None else "No starter — no ratio to take",
    )
    drawn = ribbon.ribbon(
        [series],
        start=start,
        end=end,
        now=now,
        tz=tz,
        busy=tuple(
            ribbon.BusyMark(start=one.start, end=one.end, label=one.label)
            for one in intervals
        ),
    )

    busy_label = None
    if peak_at is not None:
        clash = busy_service.covering(list(intervals), peak_at)
        busy_label = clash.label if clash is not None else None

    return FeedPreview(
        jar=jar,
        fed_at=fed_at,
        temp_c=temp_c,
        temp_assumed=temp_assumed,
        ratio=ratio,
        peak_h=peak_h,
        peak_at=peak_at,
        target_at=target_at,
        busy_label=busy_label,
        clamped_note=clamped_note,
        advice=advice,
        drawn=drawn,
    )
