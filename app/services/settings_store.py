"""User settings, stored one row per key."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import DEFAULT_SETTINGS, Setting


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
