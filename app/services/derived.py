"""Values computed from what was logged, never stored.

Keeping these derived means a typo in a feeding can be corrected and every
number that depends on it follows, which is the whole point of writing the
grams down rather than the ratio.
"""

from __future__ import annotations

from datetime import datetime

from app.models.feeding import Feeding
from app.models.observation import Observation


def _trim(value: float) -> str:
    """2 dp, but without trailing noise: 2.0 -> '2', 1.50 -> '1.5'."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def feeding_ratio(
    starter_g: float, flour_g: float, water_g: float
) -> str | None:
    """Normalise a feeding to starter=1, the way bakers say it: '1:2:2'.

    None when there is no starter to normalise against — a build from scratch
    has no meaningful ratio.
    """
    if starter_g <= 0:
        return None
    return f"1:{_trim(flour_g / starter_g)}:{_trim(water_g / starter_g)}"


def hydration_pct(flour_g: float, water_g: float) -> float | None:
    """Hydration *of this feed*: water as a percentage of flour.

    Deliberately not "total dough hydration": the carried-over starter brings
    its own flour and water, which this ignores. For comparing one feeding
    with the next — what this notebook is for — the feed's own figure is the
    honest one, and it is what a baker means by "feeding at 100%".
    """
    if flour_g <= 0:
        return None
    return water_g / flour_g * 100


def rise_pct(start_height_mm: float | None, height_mm: float | None) -> float | None:
    """How far the starter climbed, as a percentage of where it began."""
    if start_height_mm is None or height_mm is None or start_height_mm <= 0:
        return None
    return (height_mm - start_height_mm) / start_height_mm * 100


def feeding_total_g(feeding: Feeding) -> float:
    return feeding.starter_g + feeding.flour_g + feeding.water_g


def describe_feeding(feeding: Feeding) -> dict[str, object]:
    """Everything the templates want to show about one feeding."""
    return {
        "ratio": feeding_ratio(
            feeding.starter_g, feeding.flour_g, feeding.water_g
        ),
        "hydration_pct": hydration_pct(feeding.flour_g, feeding.water_g),
        "total_g": feeding_total_g(feeding),
    }


def describe_observation(observation: Observation) -> dict[str, object]:
    return {
        "rise_pct": rise_pct(
            observation.start_height_mm, observation.height_mm
        ),
    }


def hours_between(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 3600
