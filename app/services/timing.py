"""When will this jar peak, and how ready is it right now?

The fact this module exists for: **the cycle length is controllable.** How
long a starter takes to peak depends on how much flour it was given per gram
of starter, and how warm it is kept. At 1:1:1 and 80 °F rye peaks in about
four to six hours; at 1:5:5 it takes ten to fourteen. So the question worth
answering is not only "when is the next feed due" but "what should I feed it
so that the peak lands when I am actually home".

`predict_peak_h` answers the first direction and `solve_ratio` the second.
`readiness` turns "it was fed nine hours ago" into a band a person can act on
and a 0–1 number a curve can be drawn from.

**The formula is a heuristic, not physics.** It is a two-term fit — one term
for the feed ratio, one for temperature — calibrated against the four
rule-of-thumb figures bakers quote for rye, and nothing more. Phase E
measures each jar against it and keeps a correction factor per jar, which is
the honest way to be right about a particular jar on a particular counter.

Pure functions, no database and no ORM: a timing question is answerable from
a ratio, a temperature and a clock, which is what keeps this testable from a
handful of numbers.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

# --- The heuristic ------------------------------------------------------
#
# Reference point: rye, fed 1:1:1, held at 25.5 °C (78 °F), peaks in 5 h.
#
#   peak_h = REF_PEAK_H
#            × (1 + RATIO_K × log2(ratio))            # more flour, longer
#            × 2 ** ((REF_TEMP_C − temp_c) / Q_STEP_C)  # cooler, longer
#            × jar_factor                              # this jar, measured
#
# log2 rather than a straight multiple because doubling the flour does not
# double the time: the culture grows into it. RATIO_K = 0.43 is what lands
# 1:2:2 near 7 h and 1:5:5 near 10 h, which is what the books say.

REF_PEAK_H = 5.0
REF_TEMP_C = 25.5
RATIO_K = 0.43
#: Fermentation activity roughly doubles per 10 °C — a Q10 of 2.
Q_STEP_C = 10.0

# Outside these the heuristic is not merely imprecise, it is wrong: below
# 15 °C rye barely moves and the curve is not an exponential any more, and
# past 1:10 the starter is too dilute to behave like a feed at all. Inputs
# are clamped and the caller is told, rather than extrapolated in silence.
MIN_RATIO = 0.5
MAX_RATIO = 10.0
MIN_TEMP_C = 15.0
MAX_TEMP_C = 35.0

#: Nobody weighs out 1:4.37:4.37. Suggestions round to this.
RATIO_STEP = 0.5

# Guards the 2 ** in solve_ratio: an absurd target would otherwise overflow
# on the way to being clamped to a sane ratio anyway.
_MAX_LOG2 = 8.0

# --- Readiness bands ----------------------------------------------------
#
# All as a fraction of the predicted peak, so they hold at any cycle length.
# 0.85–1.15 is Scott's "parabolic" best-time-to-feed window.

PEAK_FROM = 0.85
PEAK_TO = 1.15
OK_TO = 1.5
PAST_TO = 2.0


class Band(enum.StrEnum):
    """How ready a jar is, in the words a baker would use.

    Not in models/enums.py because nothing stores a band: it is read off the
    clock every time it is asked for, like a rise percentage.
    """

    RISING = "rising"
    PEAK = "peak"
    OK = "ok"
    PAST = "past"
    HUNGRY = "hungry"

    @property
    def label(self) -> str:
        return {
            Band.RISING: "Rising",
            Band.PEAK: "At peak",
            Band.OK: "Still good",
            Band.PAST: "Going over",
            Band.HUNGRY: "Hungry",
        }[self]

    @property
    def blurb(self) -> str:
        """One line saying what to do about it."""
        return {
            Band.RISING: "on its way up — give it longer",
            Band.PEAK: "the best moment to feed it or build a levain",
            Band.OK: "past its best but still fine to use",
            Band.PAST: "collapsing and turning sour — feed it soon",
            Band.HUNGRY: "long overdue; it will need a feed to come back",
        }[self]

    @property
    def is_usable(self) -> bool:
        """Whether a levain built from it now would be worth building."""
        return self in (Band.PEAK, Band.OK)


# --- Clamping -----------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """Ratio and temperature as the model actually used them."""

    ratio: float
    temp_c: float
    ratio_clamped: bool = False
    temp_clamped: bool = False

    @property
    def clamped(self) -> bool:
        return self.ratio_clamped or self.temp_clamped

    @property
    def note(self) -> str | None:
        """What to tell the user when their numbers were pulled into range."""
        parts: list[str] = []
        if self.ratio_clamped:
            parts.append(f"a feed ratio of 1:{_trim(self.ratio)}")
        if self.temp_clamped:
            parts.append(f"{_trim(self.temp_c)} °C")
        if not parts:
            return None
        return (
            "Outside the range this estimate holds over, so it was worked out at "
            + " and ".join(parts)
            + "."
        )


def clamp_inputs(ratio: float, temp_c: float) -> Inputs:
    held_ratio = min(max(float(ratio), MIN_RATIO), MAX_RATIO)
    held_temp = min(max(float(temp_c), MIN_TEMP_C), MAX_TEMP_C)
    return Inputs(
        ratio=held_ratio,
        temp_c=held_temp,
        ratio_clamped=held_ratio != float(ratio),
        temp_clamped=held_temp != float(temp_c),
    )


# --- Predicting ---------------------------------------------------------


def _temp_factor(temp_c: float) -> float:
    return 2.0 ** ((REF_TEMP_C - temp_c) / Q_STEP_C)


def predict_peak_h(ratio: float, temp_c: float, jar_factor: float = 1.0) -> float:
    """Hours from a feed to that feed's peak.

    `ratio` is flour ÷ starter, the way a baker says it: a 1:5:5 feed is 5.0.
    `jar_factor` is this jar's measured correction (Phase E), 1.0 until there
    is anything to measure.
    """
    held = clamp_inputs(ratio, temp_c)
    return (
        REF_PEAK_H
        * (1.0 + RATIO_K * math.log2(held.ratio))
        * _temp_factor(held.temp_c)
        * float(jar_factor)
    )


def peak_at(
    fed_at: datetime,
    ratio: float,
    temp_c: float,
    jar_factor: float = 1.0,
) -> datetime:
    """The same answer as a moment on the clock, which is what a ribbon wants."""
    return fed_at + timedelta(hours=predict_peak_h(ratio, temp_c, jar_factor))


# --- Solving backwards --------------------------------------------------


def solve_ratio(
    target_peak_h: float, temp_c: float, jar_factor: float = 1.0
) -> float:
    """What to feed it so the peak lands `target_peak_h` from now.

    The inverse of `predict_peak_h`, rounded to a ratio someone would weigh
    out and clamped to the range the heuristic holds over. This is what turns
    "I want it at its best at one tomorrow" into "feed it 1:4:4".

    Rounding means the round trip is approximate by design: feeding the
    returned ratio lands within about half an hour of the target, which is
    finer than the model is accurate to anyway.
    """
    held_temp = clamp_inputs(MIN_RATIO, temp_c).temp_c
    divisor = REF_PEAK_H * _temp_factor(held_temp) * float(jar_factor)
    if divisor <= 0 or target_peak_h <= 0:
        return MIN_RATIO

    # target = REF × (1 + K·log2(r)) × temp × jar  ⇒  solve for log2(r).
    log2_ratio = (target_peak_h / divisor - 1.0) / RATIO_K
    log2_ratio = min(max(log2_ratio, -_MAX_LOG2), _MAX_LOG2)
    ratio = 2.0**log2_ratio

    rounded = round(ratio / RATIO_STEP) * RATIO_STEP
    return min(max(rounded, MIN_RATIO), MAX_RATIO)


# --- Readiness ----------------------------------------------------------


@dataclass(frozen=True)
class Readiness:
    """Where a jar is in its cycle: a band to act on, a number to draw."""

    band: Band
    #: 0 just after a feed, 1 at the peak, back to 0 once collapsed.
    score: float
    #: How far through the cycle, as a multiple of the predicted peak.
    fraction: float
    hours_since_feed: float
    peak_h: float

    @property
    def hours_to_peak(self) -> float:
        """Negative once the peak has been and gone."""
        return self.peak_h - self.hours_since_feed

    @property
    def label(self) -> str:
        return self.band.label


def rise_score(fraction: float) -> float:
    """The curve a fed jar traces: up to the peak, over, and down.

    One parabola through (0, 0), (1, 1) and (2, 0) — flat at the top, which
    is what makes the peak a window rather than an instant. It is zero at
    both ends for the same reason the bands are where they are: a jar is at
    the height it was fed to when it is fed, and back down there by the time
    it has been sitting twice as long as it needed.
    """
    if fraction <= 0.0 or fraction >= PAST_TO:
        return 0.0
    return min(fraction * (PAST_TO - fraction), 1.0)


def band_for(fraction: float) -> Band:
    if fraction < PEAK_FROM:
        return Band.RISING
    if fraction < PEAK_TO:
        return Band.PEAK
    if fraction < OK_TO:
        return Band.OK
    if fraction < PAST_TO:
        return Band.PAST
    return Band.HUNGRY


def readiness(hours_since_feed: float, peak_h: float) -> Readiness:
    """Turn "fed nine hours ago, peaks in ten" into something actionable."""
    if peak_h <= 0:
        raise ValueError("peak_h must be positive")
    fraction = max(float(hours_since_feed), 0.0) / float(peak_h)
    return Readiness(
        band=band_for(fraction),
        score=rise_score(fraction),
        fraction=fraction,
        hours_since_feed=float(hours_since_feed),
        peak_h=float(peak_h),
    )


# --- Cycles and ratios in the language of the forms ---------------------


def cycle_hours(feeds_per_day: int) -> float:
    """How long one feeding cycle is, from feeds a day."""
    if feeds_per_day <= 0:
        raise ValueError("feeds_per_day must be positive")
    return 24.0 / float(feeds_per_day)


def feed_ratio(starter_g: float, flour_g: float) -> float | None:
    """Flour ÷ starter for a logged feeding, which is what `ratio` means here.

    None for a build with no starter carried over: there is no ratio to take.
    """
    if starter_g is None or flour_g is None or starter_g <= 0:
        return None
    return float(flour_g) / float(starter_g)


def ratio_label(ratio: float) -> str:
    """"1:4:4" — a ratio as a baker writes it, at 100% hydration."""
    text = _trim(ratio)
    return f"1:{text}:{text}"


def _trim(value: float) -> str:
    """One decimal place, without the noise: 4.0 -> '4', 4.50 -> '4.5'."""
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text or "0"
