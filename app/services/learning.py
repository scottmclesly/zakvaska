"""Learning how fast each jar really is.

Everything this notebook predicts about a jar comes out of one formula with
one reference point: five hours to peak at a 1:1:1 feed and 25.5 °C
(`services.timing`). That is a reasonable rye starter, which is not the same
thing as *this* rye starter. Scott's whole experiment is two jars side by
side, so the one number that matters most is how each of them differs from
that reference — and the only way to know it is for someone to look at the
jar and say "that is its peak, now".

So this module does one thing: it reads back every time anyone recorded a
peak, works out how long the jar really took against how long the model said
it would, and averages those ratios into a single `factor` that every
prediction is multiplied by. A factor of 1.2 means this jar peaks about a
fifth later than the model expects of any jar.

Two things count as a recorded peak, and they are the same measurement:

* an observation tapped "Peaked now", read against the feeding before it;
* a bake's levain rise answered "yes, at its peak", read against what the
  model predicted for it before any correction was applied — which is why
  `bake_stage_log.model_min` is kept.

Deliberate choices worth knowing about:

* **Newest first, exponentially weighted.** A jar changes: it is fed
  different flour, it lives somewhere warmer, it matures. The last peak is
  worth more than the one before it, and five of them is as far back as
  anything is allowed to speak from.
* **Clamped, twice.** No single cycle, and no final factor, may say the jar
  is more than twice or less than half the model's speed. Someone tapping
  "Peaked now" the morning after they meant to is a real thing that happens,
  and one forgotten tap should not take the predictions with it.
* **Honest below three.** One peak is a data point, not a calibration, so
  predictions stay labelled an estimate until a jar has three.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bake import Bake, BakeStageLog
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.observation import Observation
from app.services import settings_store, timing

#: How many recorded peaks are allowed to speak. Older ones are about a jar
#: that no longer quite exists.
MAX_PEAKS = 5

#: Each step back halves-ish the say a peak has. The newest carries about
#: 43% of the weight on its own.
WEIGHT_DECAY = 0.6

#: Below this many peaks, a prediction is an estimate and says so.
CONFIDENT_AT = 3

#: The same bounds as the final factor, applied to each cycle: one tap
#: recorded hours late cannot drag everything with it.
MIN_FACTOR = 0.5
MAX_FACTOR = 2.0

#: A difference smaller than this is not worth a sentence on the page.
NOTABLE_PCT = 8.0


class PeakSource(enum.StrEnum):
    """Where a recorded peak came from."""

    OBSERVATION = "observation"
    LEVAIN = "levain"

    @property
    def label(self) -> str:
        return {
            PeakSource.OBSERVATION: "watched in the jar",
            PeakSource.LEVAIN: "a levain built for a bake",
        }[self]


@dataclass(frozen=True)
class Peak:
    """One recorded peak: how long it took against how long was predicted."""

    at: datetime
    observed_h: float
    predicted_h: float
    source: PeakSource

    @property
    def raw_ratio(self) -> float:
        """Observed over predicted, before it is reined in."""
        return self.observed_h / self.predicted_h

    @property
    def ratio(self) -> float:
        """What this cycle is allowed to say about the jar."""
        return min(max(self.raw_ratio, MIN_FACTOR), MAX_FACTOR)

    @property
    def was_clamped(self) -> bool:
        return abs(self.raw_ratio - self.ratio) > 1e-9

    @property
    def percent_off(self) -> float:
        return (self.ratio - 1.0) * 100.0


@dataclass(frozen=True)
class JarLearning:
    """What this jar's recorded peaks add up to."""

    jar: Jar
    factor: float
    peaks: tuple[Peak, ...]

    @property
    def count(self) -> int:
        return len(self.peaks)

    @property
    def has_data(self) -> bool:
        return bool(self.peaks)

    @property
    def is_confident(self) -> bool:
        """Enough peaks to call a prediction a prediction."""
        return self.count >= CONFIDENT_AT

    @property
    def percent_off(self) -> float:
        """How far from the model this jar is, as a percentage."""
        return (self.factor - 1.0) * 100.0

    @property
    def is_notable(self) -> bool:
        """Whether the difference is big enough to be worth mentioning."""
        return self.has_data and abs(self.percent_off) >= NOTABLE_PCT

    @property
    def blurb(self) -> str | None:
        """The one sentence the jar page shows. None when there is nothing
        honest to say yet."""
        if not self.has_data:
            return None
        if not self.is_notable:
            return (
                f"{self.jar.name} peaks about when the model expects, over "
                f"{self._cycles}."
            )
        direction = "later" if self.percent_off > 0 else "sooner"
        return (
            f"{self.jar.name} peaks about {abs(self.percent_off):.0f}% "
            f"{direction} than the model expects, over {self._cycles}."
        )

    @property
    def caveat(self) -> str | None:
        """Why a prediction is only an estimate, when it is."""
        if self.is_confident:
            return None
        if not self.has_data:
            return (
                "No peak has been recorded for this jar yet, so every time "
                "here is the model's guess rather than this jar's own "
                "behaviour. Tapping “Peaked now” when it is at its "
                "best is what fixes that."
            )
        return (
            f"Only {self._cycles} recorded, so these times are an estimate. "
            f"Three is where they start to mean something."
        )

    @property
    def _cycles(self) -> str:
        return f"{self.count} cycle{'' if self.count == 1 else 's'}"

    @property
    def label(self) -> str:
        """A word for how much to trust the times: shown next to them."""
        return "estimate" if not self.is_confident else "predicted"


# --- Reading the peaks back ---------------------------------------------


def _observation_peaks(
    session: Session, jar: Jar, *, default_temp_c: float, limit: int
) -> list[Peak]:
    """Peaks someone watched in the jar itself.

    Each one is read against the feeding it followed, because "took nine
    hours" only means anything next to what was fed and how warm it was.
    """
    rows = list(
        session.scalars(
            select(Observation)
            .where(Observation.jar_id == jar.id, Observation.peaked.is_(True))
            .order_by(Observation.observed_at.desc())
            .limit(limit)
        )
    )
    if not rows:
        return []

    peaks: list[Peak] = []
    for row in rows:
        feeding = session.scalars(
            select(Feeding)
            .where(Feeding.jar_id == jar.id, Feeding.fed_at <= row.observed_at)
            .order_by(Feeding.fed_at.desc(), Feeding.id.desc())
            .limit(1)
        ).first()
        if feeding is None:
            # Nothing to measure against: a peak with no feed before it says
            # how long since nothing.
            continue

        observed_h = (row.observed_at - feeding.fed_at).total_seconds() / 3600
        if observed_h <= 0:
            continue

        ratio = timing.feed_ratio(feeding.starter_g, feeding.flour_g)
        temp_c = (
            feeding.ambient_temp_c
            if feeding.ambient_temp_c is not None
            else default_temp_c
        )
        # The bare model, with no correction in it: this is the thing the
        # measurement is a measurement of.
        predicted_h = timing.predict_peak_h(
            ratio if ratio is not None else 1.0, temp_c
        )
        peaks.append(
            Peak(
                at=row.observed_at,
                observed_h=observed_h,
                predicted_h=predicted_h,
                source=PeakSource.OBSERVATION,
            )
        )
    return peaks


def _levain_peaks(session: Session, jar: Jar, *, limit: int) -> list[Peak]:
    """Peaks answered for on a bake's levain rise.

    A levain is a feed of this jar in another jar, so how long it took to
    peak measures the same culture. Read against `model_min` — what was
    predicted before any correction — so the answer cannot be a measurement
    of the correction already in force.
    """
    rows = list(
        session.scalars(
            select(BakeStageLog)
            .join(BakeStageLog.bake)
            .where(
                Bake.jar_id == jar.id,
                BakeStageLog.at_peak.is_(True),
                BakeStageLog.actual_start.is_not(None),
                BakeStageLog.actual_end.is_not(None),
            )
            .order_by(BakeStageLog.actual_end.desc())
            .limit(limit)
        )
    )

    peaks: list[Peak] = []
    for row in rows:
        base = row.model_min or row.planned_min
        actual = row.actual_min
        if not base or not actual or actual <= 0:
            continue
        peaks.append(
            Peak(
                at=row.actual_end,
                observed_h=actual / 60,
                predicted_h=base / 60,
                source=PeakSource.LEVAIN,
            )
        )
    return peaks


def recorded_peaks(
    session: Session, jar: Jar, *, limit: int = MAX_PEAKS
) -> tuple[Peak, ...]:
    """Every recorded peak for this jar, newest first, capped at `limit`.

    Both sources are pooled and then sorted, so whichever happened most
    recently carries the most weight regardless of how it was recorded.
    """
    default_temp_c = settings_store.default_ferment_temp_c(session)
    pooled = _observation_peaks(
        session, jar, default_temp_c=default_temp_c, limit=limit
    ) + _levain_peaks(session, jar, limit=limit)
    pooled.sort(key=lambda one: one.at, reverse=True)
    return tuple(pooled[:limit])


# --- Averaging them -----------------------------------------------------


def weighted_factor(peaks: Sequence[Peak]) -> float:
    """The exponentially weighted mean of the ratios, newest first.

    `peaks` must be newest first: the first one gets full weight and each
    step back is worth `WEIGHT_DECAY` of the one in front of it.
    """
    if not peaks:
        return 1.0

    total = 0.0
    weights = 0.0
    for index, peak in enumerate(peaks):
        weight = WEIGHT_DECAY**index
        total += peak.ratio * weight
        weights += weight
    return min(max(total / weights, MIN_FACTOR), MAX_FACTOR)


def learned(session: Session, jar: Jar) -> JarLearning:
    """What this jar has taught the model so far."""
    peaks = recorded_peaks(session, jar)
    return JarLearning(jar=jar, factor=weighted_factor(peaks), peaks=peaks)


def factor(session: Session, jar: Jar) -> float:
    """Just the number, for the many callers that want only that."""
    return weighted_factor(recorded_peaks(session, jar))
