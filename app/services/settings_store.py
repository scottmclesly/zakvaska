"""User settings, stored one row per key."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import (
    DEFAULT_SETTINGS,
    FEEDS_PER_DAY_CHOICES,
    RIBBON_SPAN_CHOICES,
    Setting,
)


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key)


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def all_settings(session: Session) -> dict[str, str]:
    stored = {s.key: s.value for s in session.scalars(select(Setting))}
    return {**DEFAULT_SETTINGS, **stored}


def temp_unit(session: Session) -> str:
    return (get_setting(session, "temp_unit") or "F").upper()


def weight_unit(session: Session) -> str:
    """How to show a weight: grams, US cups or US ounces and pounds."""
    from app.services.measures import METRIC, UNIT_CYCLE

    stored = get_setting(session, "weight_unit") or METRIC
    return stored if stored in UNIT_CYCLE else METRIC


# --- Timing settings ----------------------------------------------------
#
# Each one reads back as the type it means, falling back to the default when
# the stored value is missing or has been hand-edited into nonsense. A bad
# row in here must not take a page down.


def _int_setting(session: Session, key: str, choices: tuple[int, ...]) -> int:
    default = int(DEFAULT_SETTINGS[key])
    try:
        value = int(get_setting(session, key) or default)
    except (TypeError, ValueError):
        return default
    return value if value in choices else default


def feeds_per_day(session: Session) -> int:
    """How many feeds a day an active jar gets by default."""
    return _int_setting(session, "feeds_per_day", FEEDS_PER_DAY_CHOICES)


def ribbon_span_h(session: Session) -> int:
    """How many hours of timeline the ribbon shows at once."""
    return _int_setting(session, "ribbon_span_h", RIBBON_SPAN_CHOICES)


def default_ferment_temp_c(session: Session) -> float:
    """What to assume a jar is sitting at when the feeding did not say."""
    default = float(DEFAULT_SETTINGS["default_ferment_temp_c"])
    try:
        return float(get_setting(session, "default_ferment_temp_c") or default)
    except (TypeError, ValueError):
        return default


def jar_feeds_per_day(session: Session, jar) -> int:
    """This jar's rhythm: its own if it has one, otherwise the app's."""
    own = getattr(jar, "feeds_per_day", None)
    if own and own > 0:
        return int(own)
    return feeds_per_day(session)
