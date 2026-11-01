"""CLAUDE.md: store timestamps in UTC, display in JARLOG_TZ.

SQLite has no timestamp type, so a plain DateTime column hands back a *naive*
value and a later .astimezone() would silently read it as local time. These
tests pin the behaviour that prevents that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.enums import JarOrigin
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.templates_env import local_dt

NEW_YORK = ZoneInfo("America/New_York")


def _jar(session) -> Jar:
    jar = Jar(name="Test jar", origin=JarOrigin.HOMEMADE)
    session.add(jar)
    session.flush()
    return jar


def test_datetimes_come_back_timezone_aware(session):
    jar = _jar(session)
    fed_at = datetime(2026, 3, 15, 17, 30, tzinfo=UTC)
    session.add(Feeding(jar_id=jar.id, fed_at=fed_at, starter_g=20, flour_g=40, water_g=40))
    session.commit()
    session.expunge_all()

    loaded = session.get(Feeding, 1)

    assert loaded.fed_at.tzinfo is not None, "naive datetime would be read as local time"
    assert loaded.fed_at == fed_at


def test_a_non_utc_input_is_converted_before_storage(session):
    jar = _jar(session)
    # 13:30 in New York is 17:30 UTC on this date.
    local = datetime(2026, 3, 15, 13, 30, tzinfo=NEW_YORK)
    session.add(Feeding(jar_id=jar.id, fed_at=local, starter_g=20, flour_g=40, water_g=40))
    session.commit()
    session.expunge_all()

    loaded = session.get(Feeding, 1)

    assert loaded.fed_at == local
    assert loaded.fed_at.utcoffset() == timedelta(0), "stored value should be UTC"


def test_naive_datetimes_are_rejected_rather_than_guessed(session):
    jar = _jar(session)
    session.add(
        Feeding(
            jar_id=jar.id,
            fed_at=datetime(2026, 3, 15, 17, 30),  # no tzinfo
            starter_g=20, flour_g=40, water_g=40,
        )
    )

    with pytest.raises(Exception, match="naive datetime"):
        session.flush()


def test_display_converts_utc_into_the_configured_zone(session):
    jar = _jar(session)
    session.add(
        Feeding(
            jar_id=jar.id,
            fed_at=datetime(2026, 3, 15, 17, 30, tzinfo=UTC),
            starter_g=20, flour_g=40, water_g=40,
        )
    )
    session.commit()
    session.expunge_all()

    loaded = session.get(Feeding, 1)

    # 17:30 UTC is 13:30 in New York (EDT in March).
    assert local_dt(loaded.fed_at) == "2026-03-15 13:30"
