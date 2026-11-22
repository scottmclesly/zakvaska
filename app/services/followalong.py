"""Following a bake along: a plan turned into a bake, and where it has got to.

The planner (`services.bakeplan`) answers "when would everything happen?".
This is what happens next: the plan is written down as a bake with a planned
time against every step, and from then on the question changes to "what am I
meant to be doing right now, and how far behind am I?".

Three jobs, in the order they come up on a bake day:

* `start_from_plan` copies a plan into a `bake` and its `bake_stage_log`
  rows. Copied, never referenced — the same reason the stage names and
  durations are copied out of the recipe version: the plan a loaf was baked
  to is part of the record.
* `now_view` reads the stage logs back against the clock, so the bake page
  can say what is underway, what is next to do, and what the plan has
  drifted into. Nothing is stored for this; it is all arithmetic on the
  times already written down.
* `replan` moves every step that has not happened yet, chaining them from
  this moment. Planned times are the only thing it touches, so the actual
  times — what really happened — stay exactly as they were tapped in.

Conflicts are deliberately *not* stored. Busy blocks can be edited after a
bake has started, and a step that clashes with a sleep block only clashes
while that block is there, so the running sheet asks `bakeplan.conflict_for`
again on every render. One rule, so a plan and a bake underway cannot
disagree about what lands in the night.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.bake import Bake, BakeStageLog
from app.models.enums import BakeMethod, BakeStatus
from app.models.recipe import RecipeVersion
from app.services import bakeplan
from app.services import busy as busy_service
from app.services.bakeplan import BakePlan, Step, StepSpec
from app.services.busy import BusyInterval

#: The planner's waiting step is the gap *before* the bake, not a step of
#: it, so it is not written down as one. The bake simply starts when the
#: first real step does.
NOT_A_STEP = ("wait",)

#: Which generated step is the one whose length actually measures the jar.
LEVAIN_STEP = "levain_rise"


# --- A plan, written down -----------------------------------------------


def start_from_plan(
    session: Session,
    *,
    version: RecipeVersion,
    plan: BakePlan,
    now: datetime,
    jar_id: int | None = None,
    method: BakeMethod = BakeMethod.OVEN,
    equipment_program_id: int | None = None,
    crust_setting: str | None = None,
    loaf_size: str | None = None,
    oven_temp_c: float | None = None,
    total_flour_g: float | None = None,
) -> Bake:
    """Create a bake carrying the plan's times, step by step.

    A plan that starts now (or started a moment ago) makes a bake already
    in progress. A plan for tomorrow morning makes a planned one: the times
    are written down and the alerts will fire from them, but nothing is
    pretended to have begun.
    """
    steps = tuple(one for one in plan.steps if one.key not in NOT_A_STEP)
    begins = _whole_minute(steps[0].start if steps else plan.start)
    underway = begins <= now

    bake_min = None
    baking = next((one for one in steps if one.key == "bake"), None)
    if baking is not None:
        bake_min = round(baking.duration_min)

    bake = Bake(
        recipe_version_id=version.id,
        jar_id=jar_id,
        method=method,
        equipment_program_id=equipment_program_id,
        crust_setting=crust_setting,
        loaf_size=loaf_size,
        oven_temp_c=oven_temp_c,
        bake_min=bake_min,
        total_flour_g=total_flour_g,
        started_at=begins if underway else None,
        status=BakeStatus.IN_PROGRESS if underway else BakeStatus.PLANNED,
    )
    session.add(bake)
    session.flush()

    # Chained from the rounded minutes rather than copied off the plan, so
    # one step's planned end is exactly the next one's planned start. The
    # plan works in fractions of a minute; a written-down plan that left
    # fifteen-second gaps between its steps would have moments falling
    # between two of them, and "what is on right now" would find nothing.
    at = begins
    for seq, step in enumerate(steps):
        minutes = round(step.duration_min)
        session.add(
            BakeStageLog(
                bake_id=bake.id,
                seq=seq,
                name=step.name,
                step_key=step.key,
                planned_min=minutes,
                model_min=(
                    round(step.spec.model_min)
                    if step.spec.model_min is not None
                    else None
                ),
                planned_temp_c=oven_temp_c if step.key == "bake" else None,
                planned_start=at,
                hands_on=step.hands_on,
                must_be_home=step.must_be_home,
            )
        )
        at += timedelta(minutes=minutes)
    session.flush()
    session.refresh(bake)
    return bake


def _whole_minute(moment: datetime) -> datetime:
    """Planned times are read off a clock, so they live on whole minutes."""
    return moment.replace(second=0, microsecond=0)


# --- Reading the plan back off the bake ---------------------------------


def planned_steps(
    bake: Bake, *, busy: Sequence[BusyInterval] = ()
) -> tuple[Step, ...]:
    """The bake's planned steps, as the planner's own `Step`s.

    Which means the same timeline drawing and the same conflict rule serve
    a plan on the /plan page and a bake already in the oven.
    """
    intervals = list(busy)
    steps: list[Step] = []
    for log in bake.stage_logs:
        if log.planned_start is None:
            continue
        spec = StepSpec(
            key=log.step_key or f"stage-{log.seq}",
            name=log.name,
            duration_min=float(log.planned_min or 0),
            hands_on=log.hands_on,
            must_be_home=log.must_be_home,
        )
        end = log.planned_end or log.planned_start
        steps.append(
            Step(
                spec=spec,
                start=log.planned_start,
                end=end,
                conflict=bakeplan.conflict_for(
                    spec, log.planned_start, end, intervals
                ),
            )
        )
    return tuple(steps)


def has_plan(bake: Bake) -> bool:
    return any(log.planned_start is not None for log in bake.stage_logs)


@dataclass(frozen=True)
class Clash:
    """A step still to come that lands somewhere the baker is not.

    `moment` is the part of it that actually clashes — the start of a job,
    the end of a rise — because that is the time worth printing. Saying a
    five-hour rise clashes "at 20:28" when what clashes is its 03:03 finish
    would send someone to bed reassured.
    """

    log: BakeStageLog
    block: BusyInterval
    at_end: bool

    @property
    def moment(self) -> datetime | None:
        if self.at_end:
            return self.log.planned_end
        return self.log.planned_start

    @property
    def label(self) -> str:
        return self.block.label


@dataclass(frozen=True)
class NowView:
    """Where a bake has got to, this minute."""

    now: datetime
    #: Ticked started and not yet ended. The truth, where there is one.
    running: BakeStageLog | None
    #: What the plan says should be happening, which may not be the above.
    due_now: BakeStageLog | None
    #: The first step not yet done, whether or not its time has come.
    next_up: BakeStageLog | None
    #: The next one that actually needs Scott in the kitchen.
    next_hands_on: BakeStageLog | None
    #: Steps still to come that land somewhere he is busy.
    clashes: tuple[Clash, ...] = ()
    #: How far past its planned end the bake has drifted, in minutes.
    behind_min: float | None = None
    #: When the last planned step ends.
    ends_at: datetime | None = None
    #: A finished levain rise that has not been asked about yet.
    ask_peak: BakeStageLog | None = None

    @property
    def current(self) -> BakeStageLog | None:
        """The one step to put at the top of the page."""
        return self.running or self.due_now or self.next_up

    @property
    def is_behind(self) -> bool:
        return self.behind_min is not None and self.behind_min >= 1

    @property
    def is_done(self) -> bool:
        return self.next_up is None


def now_view(
    bake: Bake, *, now: datetime, busy: Sequence[BusyInterval] = ()
) -> NowView:
    """Read the stage logs against the clock. Writes nothing."""
    logs = list(bake.stage_logs)
    intervals = list(busy)

    running = next((log for log in logs if log.is_running), None)
    pending = [log for log in logs if not log.is_done]

    due_now = next(
        (
            log
            for log in pending
            if log.planned_start is not None
            and log.planned_end is not None
            and log.planned_start <= now < log.planned_end
        ),
        None,
    )
    next_up = pending[0] if pending else None
    # The steps are in order and the done ones are gone, so the first
    # hands-on one left is the next thing to do — even if its hour has
    # already gone by, which only means it is late.
    next_hands_on = next((log for log in pending if log.hands_on), None)

    clashes: list[Clash] = []
    for log in pending:
        if log.planned_start is None:
            continue
        end = log.planned_end or log.planned_start
        spec = StepSpec(
            key=log.step_key or "",
            name=log.name,
            duration_min=float(log.planned_min or 0),
            hands_on=log.hands_on,
            must_be_home=log.must_be_home,
        )
        found = bakeplan.conflict_for(spec, log.planned_start, end, intervals)
        if found is not None:
            # A hands-on step clashes because the work falls in the block;
            # anything else clashes because its finish does.
            clashes.append(
                Clash(
                    log=log,
                    block=found,
                    at_end=not (log.hands_on and found.overlaps(
                        log.planned_start, end
                    )),
                )
            )

    behind = None
    reference = running or next_up
    if reference is not None:
        # A running step is late once it is past the end it was planned for;
        # an unstarted one is late once its start has gone by.
        moment = (
            reference.planned_end if reference is running else reference.planned_start
        )
        if moment is not None and now > moment:
            behind = (now - moment).total_seconds() / 60

    ends = [log.planned_end for log in logs if log.planned_end is not None]

    return NowView(
        now=now,
        running=running,
        due_now=due_now,
        next_up=next_up,
        next_hands_on=next_hands_on,
        clashes=tuple(clashes),
        behind_min=behind,
        ends_at=max(ends) if ends else None,
        ask_peak=peak_to_ask(bake),
    )


# --- Moving the rest of the day -----------------------------------------


def replan(session: Session, bake: Bake, *, now: datetime) -> int:
    """Chain every step that has not happened yet from this moment.

    Returns how many planned times actually moved. A step already finished
    is never touched: what happened, happened. A step underway keeps the
    start it really had, and the rest of the day picks up either when that
    step was due to end or now, whichever is later — so a rise an hour into
    its five pushes the evening back four hours, while one that has already
    overrun pushes it to now.

    Conflicts are not recomputed here because they are never stored; the
    page asks about them again on the way out.
    """
    moved = 0
    at = now
    for log in bake.stage_logs:
        if log.is_done:
            continue
        if log.is_running:
            if log.planned_start != log.actual_start:
                log.planned_start = log.actual_start
                moved += 1
            projected = log.actual_start + timedelta(
                minutes=float(log.planned_min or 0)
            )
            at = max(now, projected)
            continue
        if log.planned_start != at:
            log.planned_start = at
            moved += 1
        at += timedelta(minutes=float(log.planned_min or 0))

    session.flush()
    return moved


# --- The one question worth asking ---------------------------------------


def peak_to_ask(bake: Bake) -> BakeStageLog | None:
    """A levain rise that has ended and not been asked about.

    The honest measurement of how fast a jar is comes from someone looking
    at the jar, which is why the bake page asks rather than assuming the
    tap meant the levain was ready. Phase E is what reads the answers back.
    """
    return next(
        (
            log
            for log in bake.stage_logs
            if log.step_key == LEVAIN_STEP
            and log.is_done
            and log.at_peak is None
        ),
        None,
    )


def answer_peak(
    session: Session, log: BakeStageLog, *, at_peak: bool
) -> BakeStageLog:
    log.at_peak = at_peak
    session.flush()
    return log


# --- What the alerts need ------------------------------------------------

#: A step whose moment went by this long ago has been missed, not forgotten:
#: the bake has moved on without the app and nagging about it helps nobody.
STAGE_GRACE_H = 6.0

#: A step you can see through standing there needs no second alert when it
#: ends. Longer than this and you will have left the room, so the end is
#: worth being interrupted for: this is the difference between a ten-minute
#: shaping and a five-hour rise that has to be used the moment it is ready.
LEAVE_THE_ROOM_MIN = 20.0


def stage_due_moments(log: BakeStageLog) -> tuple[datetime, ...]:
    """The moments this step is worth interrupting someone for.

    A hands-on step at its start, because that is when the work begins. A
    must-be-home step at its end, because that is the moment a rise has to
    be used or a loaf taken out — but only if it ran long enough that
    anyone would have wandered off. Baking is both: one alert to put it in,
    another three quarters of an hour later to take it out.
    """
    if log.planned_start is None or log.is_done:
        return ()

    moments: list[datetime] = []
    if log.hands_on:
        moments.append(log.planned_start)
    if log.must_be_home and float(log.planned_min or 0) >= LEAVE_THE_ROOM_MIN:
        end = log.planned_end
        if end is not None and end not in moments:
            moments.append(end)
    return tuple(moments)


def live_bakes(session: Session) -> list[Bake]:
    """Bakes whose steps could still come due."""
    return list(
        session.scalars(
            select(Bake)
            .where(
                Bake.archived.is_(False),
                Bake.status.in_((BakeStatus.PLANNED, BakeStatus.IN_PROGRESS)),
            )
            .options(selectinload(Bake.stage_logs))
        )
    )


def busy_for(
    session: Session, bake: Bake, *, now: datetime, tz: tzinfo
) -> list[BusyInterval]:
    """The busy blocks covering this bake's planned span, plus some air."""
    starts = [log.planned_start for log in bake.stage_logs if log.planned_start]
    ends = [log.planned_end for log in bake.stage_logs if log.planned_end]
    first = min(starts + [now]) if starts else now
    last = max(ends + [now]) if ends else now + timedelta(days=1)
    return busy_service.busy_intervals(
        session, first - timedelta(hours=2), last + timedelta(hours=2), tz
    )
