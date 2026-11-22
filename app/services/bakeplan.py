"""The bake-day planner: "if I start now, when does everything happen?"

A bake day is a chain of steps whose clock times Scott cannot see in advance,
which is the second half of the timing problem this notebook has. Given a
recipe, a jar and a starting time, this says when each step falls, which ones
need him in the kitchen, and which of those land in the hours he is asleep.

Two directions, one answer. **Forward** from a start time, and **backward**
from "I want bread by six" — and the backward one is simply the forward one
started earlier, which is why the steps are worked out as a chain of
durations first and only then laid on a clock. One layout function, so the
two directions cannot drift apart; the test that proves it asserts the same
plan comes out of both.

Nothing here is stored. A plan is recomputed from its inputs every time,
which is what lets the start-time slider scrub it live, and Phase D is what
turns one into a bake with its times written down.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.enums import IngredientRole
from app.models.jar import Jar
from app.models.recipe import EquipmentProgram, RecipeVersion
from app.services import busy as busy_service
from app.services import plan as plan_service
from app.services import scaling, settings_store, timing
from app.services.busy import BusyInterval
from app.services.timing import Band

# --- Defaults, all overridable on the form ------------------------------

#: A levain is built tighter than a maintenance feed: it wants to be ready
#: in an afternoon, not overnight.
DEFAULT_LEVAIN_RATIO = 2.0
#: Building the levain and feeding the main jar, together.
LEVAIN_BUILD_MIN = 10.0
#: Getting everything into the machine.
LOAD_MIN = 5.0
#: Kneading by hand, or a machine with no program typed in.
DEFAULT_KNEAD_MIN = 25.0
SHAPE_MIN = 10.0
#: Commercial yeast is quick; a starter-only pan loaf is not.
FINAL_RISE_YEAST_MIN = 150.0
FINAL_RISE_STARTER_MIN = 300.0
DEFAULT_BAKE_MIN = 45.0
#: Rye in particular must be cold before it is cut, or it gums up.
DEFAULT_COOL_MIN = 120.0
#: Bagging it is two minutes, but it is two minutes that has to be remembered.
BAG_MIN = 2.0

#: How far "find a time that works" looks, and how finely.
SEARCH_HOURS = 48
SEARCH_STEP_MIN = 15

#: Recipe stage names that stand in for a generated step. Matched as
#: lowercase substrings, so "final proof (in the pan)" finds "proof".
STAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "levain_rise": ("levain", "sponge", "starter"),
    "knead": ("knead", "mix"),
    "final_rise": ("final rise", "final proof", "proof", "bulk ferment"),
    "bake": ("bake",),
    "cool": ("cool",),
}


# --- What goes in -------------------------------------------------------


@dataclass(frozen=True)
class PlanInputs:
    """Everything the planner needs. Defaults come from `default_inputs`."""

    total_flour_g: float | None = None
    #: Forward from here. Ignored when `ready_by` is set.
    start_at: datetime | None = None
    #: Backward from here: the moment the bread is cool and bagged.
    ready_by: datetime | None = None

    levain_ratio: float = DEFAULT_LEVAIN_RATIO
    levain_temp_c: float = 26.7
    levain_g: float | None = None

    program_id: int | None = None
    loaf_lb: float | None = None
    #: Scott's method: the machine kneads and he takes it from there.
    knead_only: bool = True
    #: Used when there is no program, or no program was chosen.
    knead_min: float | None = None

    final_rise_min: float | None = None
    bake_temp_c: float | None = None
    bake_min: float | None = None
    cool_min: float = DEFAULT_COOL_MIN

    @property
    def is_backward(self) -> bool:
        return self.ready_by is not None


# --- What comes out -----------------------------------------------------


@dataclass(frozen=True)
class StepSpec:
    """One step as a duration, before it is put on a clock."""

    key: str
    name: str
    duration_min: float
    hands_on: bool = False
    must_be_home: bool = False
    note: str | None = None
    #: True when a recipe stage supplied the duration instead of a default.
    from_recipe: bool = False


@dataclass(frozen=True)
class Step:
    """One step, on the clock."""

    spec: StepSpec
    start: datetime
    end: datetime
    #: The busy block this step clashes with, if it clashes with one.
    conflict: BusyInterval | None = None

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def duration_min(self) -> float:
        return self.spec.duration_min

    @property
    def hands_on(self) -> bool:
        return self.spec.hands_on

    @property
    def must_be_home(self) -> bool:
        return self.spec.must_be_home

    @property
    def clashes(self) -> bool:
        return self.conflict is not None

    @property
    def duration_label(self) -> str:
        return timing.hours_label(self.duration_min / 60)


@dataclass(frozen=True)
class BakePlan:
    steps: tuple[Step, ...]
    start: datetime
    end: datetime
    #: Things worth saying that are not conflicts: an unready jar, say.
    warnings: tuple[str, ...] = ()
    levain_g: float | None = None
    levain_peak_h: float | None = None

    @property
    def total_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    @property
    def total_label(self) -> str:
        return timing.hours_label(self.total_min / 60)

    @property
    def conflicts(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.clashes)

    @property
    def works(self) -> bool:
        return not self.conflicts

    @property
    def hands_on_min(self) -> float:
        return sum(step.duration_min for step in self.steps if step.hands_on)

    def step(self, key: str) -> Step | None:
        return next((one for one in self.steps if one.key == key), None)

    def at(self, moment: datetime) -> Step | None:
        """The step underway at a given instant, for Phase D's Now panel."""
        for one in self.steps:
            if one.start <= moment < one.end:
                return one
        return None


# --- Reading the recipe -------------------------------------------------


def _stage_minutes(version: RecipeVersion | None, key: str) -> float | None:
    """A recipe stage's own duration, where the recipe has one for this step.

    The plan generates a sensible chain; a recipe that actually says how long
    its proof takes knows better, so it wins.
    """
    if version is None:
        return None
    for alias in STAGE_ALIASES.get(key, ()):
        for stage in version.stages:
            if alias in stage.name.lower() and stage.duration_min:
                return float(stage.duration_min)
    return None


def _has_commercial_yeast(version: RecipeVersion | None) -> bool:
    if version is None:
        return False
    return any("yeast" in one.name.lower() for one in version.ingredients)


def _levain_grams(
    version: RecipeVersion | None, total_flour_g: float | None
) -> float | None:
    """How much levain the recipe calls for, at this batch size."""
    if version is None or not total_flour_g:
        return None
    scaled = scaling.scale_to_flour(version.ingredients, total_flour_g)
    grams = sum(
        one.grams
        for one in scaled.ingredients
        if one.role is IngredientRole.LEVAIN
    )
    return grams or None


def _knead_minutes(
    program: EquipmentProgram | None, loaf_lb: float | None, inputs: PlanInputs
) -> tuple[float, str | None]:
    """Kneading time, and a note saying where it came from.

    The manual's own figures when there is a program: knead, rest, knead —
    the machine's clock differs for a 2 lb loaf and a 3 lb one, which is why
    the cycles are stored per size rather than as one total.
    """
    if program is not None:
        cycle = program.cycle_for(loaf_lb) or (
            program.cycles[0] if program.cycles else None
        )
        if cycle is not None:
            parts = [cycle.knead1_min, cycle.rest_min, cycle.knead2_min]
            total = sum(float(one) for one in parts if one)
            if total:
                return total, f"{program.name} — knead, rest, knead"
    if inputs.knead_min:
        return float(inputs.knead_min), None
    return DEFAULT_KNEAD_MIN, "no program chosen, so a rough estimate"


def _program_total_minutes(
    program: EquipmentProgram | None, loaf_lb: float | None
) -> float | None:
    if program is None:
        return None
    cycle = program.cycle_for(loaf_lb) or (
        program.cycles[0] if program.cycles else None
    )
    if cycle is None:
        return None
    return float(cycle.total_min) if cycle.total_min else None


# --- The chain of steps -------------------------------------------------


def step_specs(
    inputs: PlanInputs,
    *,
    version: RecipeVersion | None = None,
    program: EquipmentProgram | None = None,
) -> tuple[StepSpec, ...]:
    """The bake as a chain of durations, before any clock is involved.

    Deliberately start-time-independent: this is what makes back-scheduling
    the same arithmetic as forward scheduling rather than a second
    implementation of it. The one start-dependent step — waiting for the jar
    to come good — is added by `lay_out`.
    """
    specs: list[StepSpec] = []

    levain_peak_h = timing.predict_peak_h(
        inputs.levain_ratio, inputs.levain_temp_c
    )
    levain_rise_min = _stage_minutes(version, "levain_rise")
    specs.append(
        StepSpec(
            key="levain",
            name="Build the levain, and feed the jar",
            duration_min=LEVAIN_BUILD_MIN,
            hands_on=True,
            must_be_home=True,
            note="while the jar is at its best",
        )
    )
    specs.append(
        StepSpec(
            key="levain_rise",
            name="Levain rises to its peak",
            duration_min=(
                levain_rise_min
                if levain_rise_min is not None
                else levain_peak_h * 60
            ),
            # Passive, but it has to be used at the end or it goes over.
            must_be_home=True,
            note=(
                f"{timing.ratio_label(inputs.levain_ratio)} at "
                f"{inputs.levain_temp_c:.0f} °C"
            ),
            from_recipe=levain_rise_min is not None,
        )
    )

    knead_min, knead_note = _knead_minutes(program, inputs.loaf_lb, inputs)
    stage_knead = _stage_minutes(version, "knead")
    specs.append(
        StepSpec(
            key="load",
            name="Mix, and load the machine",
            duration_min=LOAD_MIN,
            hands_on=True,
            must_be_home=True,
        )
    )

    if inputs.knead_only or program is None:
        specs.append(
            StepSpec(
                key="knead",
                name="Kneading",
                duration_min=stage_knead if stage_knead is not None else knead_min,
                note=knead_note,
                from_recipe=stage_knead is not None,
            )
        )

        final_rise_min = (
            inputs.final_rise_min
            if inputs.final_rise_min is not None
            else _stage_minutes(version, "final_rise")
        )
        if final_rise_min is None:
            final_rise_min = (
                FINAL_RISE_YEAST_MIN
                if _has_commercial_yeast(version)
                else FINAL_RISE_STARTER_MIN
            )

        specs.append(
            StepSpec(
                key="shape",
                name="Shape into the greased pan",
                duration_min=SHAPE_MIN,
                hands_on=True,
                must_be_home=True,
            )
        )
        specs.append(
            StepSpec(
                key="final_rise",
                name="Final rise in the pan",
                duration_min=float(final_rise_min),
                must_be_home=True,
                note="until about one and a half times its size",
                from_recipe=inputs.final_rise_min is None
                and _stage_minutes(version, "final_rise") is not None,
            )
        )

        bake_min = (
            inputs.bake_min
            if inputs.bake_min is not None
            else _stage_minutes(version, "bake")
        )
        specs.append(
            StepSpec(
                key="bake",
                name="Bake",
                duration_min=float(
                    bake_min if bake_min is not None else DEFAULT_BAKE_MIN
                ),
                hands_on=True,
                must_be_home=True,
                note=(
                    f"{inputs.bake_temp_c:.0f} °C"
                    if inputs.bake_temp_c is not None
                    else None
                ),
                from_recipe=inputs.bake_min is None
                and _stage_minutes(version, "bake") is not None,
            )
        )
    else:
        # The machine runs the whole program: knead, rise, knock back, rise,
        # bake. Nothing to do but come back for it.
        whole = _program_total_minutes(program, inputs.loaf_lb)
        specs.append(
            StepSpec(
                key="program",
                name=f"{program.name} runs",
                duration_min=whole if whole else knead_min,
                must_be_home=True,
                note="the machine does the rest",
            )
        )

    cool_min = _stage_minutes(version, "cool")
    specs.append(
        StepSpec(
            key="cool",
            name="Cool on a rack",
            duration_min=float(
                cool_min if cool_min is not None else inputs.cool_min
            ),
            note="rye gums up if it is cut warm",
            from_recipe=cool_min is not None,
        )
    )
    specs.append(
        StepSpec(
            key="bag",
            name="Bag it",
            duration_min=BAG_MIN,
            hands_on=True,
        )
    )
    return tuple(specs)


def chain_minutes(specs: Sequence[StepSpec]) -> float:
    return sum(one.duration_min for one in specs)


# --- Putting it on a clock ----------------------------------------------


def _jar_wait(
    jar_plan: plan_service.JarPlan | None, start: datetime
) -> tuple[float, str | None]:
    """How long to wait for the jar to be worth building a levain from.

    Zero when it is already in its peak or still-good band. A jar past its
    best cannot be waited into usefulness — it needs feeding — so that comes
    back as a warning rather than a wait nobody should sit through.
    """
    if jar_plan is None or jar_plan.last_cycle is None:
        return 0.0, None

    cycle = jar_plan.last_cycle
    ready = cycle.readiness_at(start)
    if ready.band.is_usable:
        return 0.0, None
    if ready.band is Band.RISING:
        # Wait until the peak window opens.
        opens = cycle.fed_at + timedelta(
            hours=cycle.peak_h * timing.PEAK_FROM
        )
        minutes = max((opens - start).total_seconds() / 60, 0.0)
        return minutes, None
    return 0.0, (
        f"{jar_plan.jar.name} is {ready.band.label.lower()} at that time — "
        "feed it and build the levain from the next peak instead."
    )


def conflict_for(
    spec: StepSpec,
    start: datetime,
    end: datetime,
    intervals: Sequence[BusyInterval],
) -> BusyInterval | None:
    """Whether a step at this time lands somewhere the baker is not.

    The rule, from the plan: a **hands-on** step clashes if any of it falls
    in a busy block — it is work, and work needs doing. A **must-be-home**
    step clashes only if its *end* does, because a rise minds nobody being
    there until the moment it is ready.

    One function, because a planned bake and a bake already underway must
    agree about what clashes: the running sheet re-checks a step that has
    been moved by exactly this rule.
    """
    if spec.hands_on:
        clashes = busy_service.overlapping(intervals, start, end)
        if clashes:
            return clashes[0]
    if spec.must_be_home:
        return busy_service.covering(intervals, end)
    return None


def lay_out(
    specs: Sequence[StepSpec],
    start: datetime,
    *,
    busy: Sequence[BusyInterval] = (),
    jar_plan: plan_service.JarPlan | None = None,
) -> BakePlan:
    """Walk the chain forward from `start`, flagging what clashes."""
    intervals = list(busy)
    wait_min, warning = _jar_wait(jar_plan, start)

    chain: list[StepSpec] = []
    if wait_min > 0:
        chain.append(
            StepSpec(
                key="wait",
                name="Wait for the jar to come good",
                duration_min=wait_min,
                note="it is still rising at that time",
            )
        )
    chain.extend(specs)

    steps: list[Step] = []
    at = start
    for spec in chain:
        ends = at + timedelta(minutes=spec.duration_min)
        steps.append(
            Step(
                spec=spec,
                start=at,
                end=ends,
                conflict=conflict_for(spec, at, ends, intervals),
            )
        )
        at = ends

    return BakePlan(
        steps=tuple(steps),
        start=start,
        end=at,
        warnings=(warning,) if warning else (),
    )


def forward(
    specs: Sequence[StepSpec],
    start: datetime,
    *,
    busy: Sequence[BusyInterval] = (),
    jar_plan: plan_service.JarPlan | None = None,
) -> BakePlan:
    return lay_out(specs, start, busy=busy, jar_plan=jar_plan)


def backward(
    specs: Sequence[StepSpec],
    ready_by: datetime,
    *,
    busy: Sequence[BusyInterval] = (),
    jar_plan: plan_service.JarPlan | None = None,
) -> BakePlan:
    """The same plan, worked out from when the bread should be ready.

    The start time is the deadline less the chain, so this *is* the forward
    layout from an earlier moment rather than a second implementation of the
    arithmetic. With a jar that is ready, the two directions produce an
    identical plan — which is what the equivalence test asserts.

    The jar's waiting time is deliberately not folded in here: waiting would
    push the bread past the hour that was asked for, and a plan that quietly
    misses its deadline is worse than one that says it cannot be met.
    """
    start = ready_by - timedelta(minutes=chain_minutes(specs))
    made = lay_out(specs, start, busy=busy, jar_plan=None)

    wait_min, warning = _jar_wait(jar_plan, start)
    notes: list[str] = []
    if warning:
        notes.append(warning)
    elif wait_min > 0:
        notes.append(
            "The jar will still be rising then, so the levain would be built "
            f"about {timing.hours_label(wait_min / 60)} early. Bread this soon "
            "means a levain that has not peaked."
        )
    return replace(made, warnings=tuple(notes))


# --- Finding a time that works ------------------------------------------


@dataclass(frozen=True)
class Candidate:
    start: datetime
    plan: BakePlan


def find_workable(
    specs: Sequence[StepSpec],
    *,
    from_moment: datetime,
    busy: Sequence[BusyInterval] = (),
    jar_plan: plan_service.JarPlan | None = None,
    hours: int = SEARCH_HOURS,
    step_min: int = SEARCH_STEP_MIN,
) -> Candidate | None:
    """The earliest start in the next `hours` with nothing clashing.

    Brute force on a quarter-hour grid — 192 layouts for two days, each a
    walk down a list of ten steps, which is nothing next to the page it is
    rendered into and far easier to be sure of than a cleverer search.
    """
    at = _ceil_to_step(from_moment, step_min)
    limit = from_moment + timedelta(hours=hours)
    while at <= limit:
        made = lay_out(specs, at, busy=busy, jar_plan=jar_plan)
        if made.works:
            return Candidate(start=at, plan=made)
        at += timedelta(minutes=step_min)
    return None


def _ceil_to_step(moment: datetime, step_min: int) -> datetime:
    """Round up to the next quarter hour, so suggestions are sayable times."""
    discard = timedelta(
        minutes=moment.minute % step_min,
        seconds=moment.second,
        microseconds=moment.microsecond,
    )
    if discard:
        return moment - discard + timedelta(minutes=step_min)
    return moment


# --- Putting it together from the database ------------------------------


def default_inputs(
    session: Session,
    version: RecipeVersion | None,
    *,
    now: datetime,
    jar: Jar | None = None,
) -> PlanInputs:
    """A plan already filled in sensibly, so the page opens on an answer."""
    total_flour = version.batch_flour_g if version else None
    bake_min = _stage_minutes(version, "bake")
    return PlanInputs(
        total_flour_g=total_flour,
        start_at=now,
        levain_ratio=DEFAULT_LEVAIN_RATIO,
        levain_temp_c=settings_store.default_ferment_temp_c(session),
        levain_g=_levain_grams(version, total_flour),
        program_id=version.default_program_id if version else None,
        loaf_lb=_loaf_lb(version.default_loaf_size if version else None),
        knead_only=True,
        bake_min=bake_min,
        cool_min=DEFAULT_COOL_MIN,
    )


def _loaf_lb(label: str | None) -> float | None:
    """"2 lb" as 2.0. The size is stored as the label the machine shows."""
    if not label:
        return None
    digits = "".join(
        char for char in label if char.isdigit() or char == "."
    )
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def build(
    session: Session,
    *,
    version: RecipeVersion | None,
    jar: Jar | None,
    inputs: PlanInputs,
    now: datetime,
    tz,
    program: EquipmentProgram | None = None,
) -> tuple[BakePlan, tuple[StepSpec, ...], Candidate | None]:
    """A laid-out plan, its step chain, and the earliest time that works.

    Returns the chain as well so the caller can search again — rebuilding it
    would mean reading the recipe twice and risking two different answers.
    """
    specs = step_specs(inputs, version=version, program=program)

    jar_plan = None
    if jar is not None:
        jar_plan = plan_service.jar_plan(
            session, jar, now=now, until=now + timedelta(days=3)
        )

    # Wide enough to cover a plan started two days out and running a day.
    window_start = now - timedelta(hours=1)
    window_end = now + timedelta(hours=SEARCH_HOURS + 48)
    intervals = busy_service.busy_intervals(session, window_start, window_end, tz)

    if inputs.is_backward:
        made = backward(
            specs, inputs.ready_by, busy=intervals, jar_plan=jar_plan
        )
    else:
        made = forward(
            specs, inputs.start_at or now, busy=intervals, jar_plan=jar_plan
        )

    levain_peak_h = timing.predict_peak_h(
        inputs.levain_ratio, inputs.levain_temp_c
    )
    made = replace(
        made, levain_g=inputs.levain_g, levain_peak_h=levain_peak_h
    )

    workable = None
    if not made.works:
        workable = find_workable(
            specs, from_moment=now, busy=intervals, jar_plan=jar_plan
        )
    return made, specs, workable
