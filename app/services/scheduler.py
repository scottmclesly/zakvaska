"""The in-process job that fires feeding alerts.

APScheduler holds no alert state of its own: every tick just calls
`alerts.reconcile`, which reads the jars and feedings and works out what
should exist. A restart therefore loses nothing — the first tick (and the
explicit run at startup) rebuilds the same picture.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import get_sessionmaker
from app.models.base import utcnow
from app.services import alerts

log = logging.getLogger("zakvaska.alerts")

JOB_ID = "reconcile_alerts"
TICK_SECONDS = 60

_scheduler: BackgroundScheduler | None = None


def reconcile_now() -> alerts.ReconcileResult:
    """One pass. Safe to call from anywhere, including at startup."""
    with get_sessionmaker()() as session:
        result = alerts.reconcile(session, utcnow())
        if result.changed:
            session.commit()
            for alert in result.fired:
                log.info("alert fired for jar %s (due %s)", alert.jar_id, alert.due_at)
        else:
            session.rollback()
        return result


def start() -> BackgroundScheduler | None:
    """Start ticking. Returns None when disabled (ZAKVASKA_SCHEDULER=0)."""
    global _scheduler

    if not get_settings().scheduler_enabled:
        log.info("alert scheduler disabled")
        return None
    if _scheduler is not None:
        return _scheduler

    # Catch up once immediately, so alerts that came due while the process
    # was down fire now rather than at the top of the next minute.
    reconcile_now()

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        reconcile_now,
        trigger=IntervalTrigger(seconds=TICK_SECONDS),
        id=JOB_ID,
        # If the machine slept, run once on waking rather than N times.
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("alert scheduler started, every %ss", TICK_SECONDS)
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
