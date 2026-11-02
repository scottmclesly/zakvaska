"""The APScheduler job itself.

Tests run with ZAKVASKA_SCHEDULER=0 (see conftest), so anything that needs a
real scheduler turns it on deliberately and shuts it down again.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.base import utcnow
from app.models.enums import JarOrigin, JarState
from app.services import alerts as alert_service
from app.services import jars as jar_service
from app.services import scheduler


@pytest.fixture
def scheduler_enabled(monkeypatch):
    monkeypatch.setenv("ZAKVASKA_SCHEDULER", "1")
    get_settings.cache_clear()
    yield
    scheduler.shutdown()
    monkeypatch.setenv("ZAKVASKA_SCHEDULER", "0")
    get_settings.cache_clear()


def overdue_jar() -> int:
    with get_sessionmaker()() as session:
        jar = jar_service.create_jar(
            session, name="Rye", origin=JarOrigin.HOMEMADE,
            state=JarState.ACTIVE, feed_interval_room_h=12,
        )
        jar_service.log_feeding(
            session, jar, fed_at=utcnow() - timedelta(hours=20),
            starter_g=20, flour_g=40, water_g=40,
        )
        session.commit()
        return jar.id


def test_reconcile_now_commits_its_work(session):
    overdue_jar()

    result = scheduler.reconcile_now()

    assert len(result.fired) == 1
    # A separate session proves it was committed, not just flushed.
    with get_sessionmaker()() as fresh:
        assert alert_service.showing(fresh, utcnow())


def test_reconcile_now_is_safe_to_call_repeatedly():
    overdue_jar()

    scheduler.reconcile_now()
    second = scheduler.reconcile_now()

    assert not second.fired
    assert not second.changed


def test_disabled_by_configuration_starts_nothing():
    assert not get_settings().scheduler_enabled
    assert scheduler.start() is None


def test_starting_registers_a_repeating_job(scheduler_enabled):
    started = scheduler.start()

    assert started is not None
    job = started.get_job(scheduler.JOB_ID)
    assert job is not None
    assert job.trigger.interval.total_seconds() == scheduler.TICK_SECONDS


def test_starting_catches_up_immediately(scheduler_enabled):
    # An alert that came due while the process was down should fire at once,
    # not at the top of the next minute.
    overdue_jar()

    scheduler.start()

    with get_sessionmaker()() as fresh:
        assert alert_service.showing(fresh, utcnow())


def test_starting_twice_returns_the_same_scheduler(scheduler_enabled):
    first = scheduler.start()
    second = scheduler.start()

    assert first is second


def test_shutdown_is_safe_when_nothing_is_running():
    scheduler.shutdown()
    scheduler.shutdown()  # must not raise


def test_the_scheduler_logs_when_an_alert_fires(caplog):
    # Nobody is watching a background job; the log is the only evidence.
    overdue_jar()

    with caplog.at_level("INFO", logger="zakvaska.alerts"):
        scheduler.reconcile_now()

    assert any("alert fired" in record.message for record in caplog.records)


def test_setup_logging_gives_our_logger_a_destination():
    import logging

    from app.logging_config import setup_logging

    logger = setup_logging()

    assert logger.handlers, "uvicorn leaves the root logger bare"
    assert logger.level == logging.INFO
