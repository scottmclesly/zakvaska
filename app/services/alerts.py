"""Feeding alerts.

The whole table is derived: `reconcile` rebuilds it from the jars and their
feedings, so it is safe to run every minute and safe to run again after a
restart. Nothing about a pending alert lives in memory, which is what makes
"restart mid-countdown still fires" true rather than hopeful.

Lifecycle of one alert:

    created (pending)  --now >= due_at-->  fired  --ack / feeding-->  done
                                             |
                                          snoozed (hidden until snoozed_until)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.alert import Alert
from app.models.enums import AlertKind
from app.models.jar import Jar
from app.services.schedule import last_feeding, next_due_at

# Offered in the UI; "custom" is any number of minutes.
SNOOZE_CHOICES = ((30, "30 min"), (120, "2 hours"))


@dataclass
class ReconcileResult:
    created: list[Alert] = field(default_factory=list)
    fired: list[Alert] = field(default_factory=list)
    dropped: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.created or self.fired or self.dropped)


def _pending_alerts(session: Session, jar_id: int) -> list[Alert]:
    return list(
        session.scalars(
            select(Alert).where(
                Alert.jar_id == jar_id,
                Alert.fired_at.is_(None),
                Alert.acknowledged_at.is_(None),
            )
        )
    )


def _drop_superseded(
    session: Session, jar_id: int, keep_due: datetime | None
) -> int:
    """Remove alerts that are waiting for a moment that will never come.

    An alert that never fired carries no history — if the jar was fed early,
    or moved to the fridge, the old prediction is simply wrong. Fired ones are
    left alone, because those did happen.
    """
    dropped = 0
    for alert in _pending_alerts(session, jar_id):
        if keep_due is None or alert.due_at != keep_due:
            session.delete(alert)
            dropped += 1
    return dropped


def reconcile(session: Session, now: datetime) -> ReconcileResult:
    """Bring the alert table in line with the jars. Idempotent."""
    result = ReconcileResult()

    jars = list(
        session.scalars(select(Jar).where(Jar.archived.is_(False)))
    )

    for jar in jars:
        previous = last_feeding(session, jar.id)
        due = next_due_at(jar, previous.fed_at if previous else None)

        # Dormant, dried, archived or never fed: nothing to chase.
        result.dropped += _drop_superseded(session, jar.id, due)
        if due is None:
            continue

        alert = session.scalars(
            select(Alert).where(
                Alert.jar_id == jar.id,
                Alert.kind == AlertKind.FEED_DUE,
                Alert.due_at == due,
            )
        ).first()

        if alert is None:
            alert = Alert(jar_id=jar.id, kind=AlertKind.FEED_DUE, due_at=due)
            session.add(alert)
            session.flush()
            result.created.append(alert)

        if alert.is_pending and now >= alert.effective_due_at:
            alert.fired_at = now
            result.fired.append(alert)

    session.flush()
    return result


def showing(session: Session, now: datetime) -> list[Alert]:
    """Alerts the user should see right now, most overdue first."""
    return list(
        session.scalars(
            select(Alert)
            .where(
                Alert.fired_at.is_not(None),
                Alert.acknowledged_at.is_(None),
                or_(Alert.snoozed_until.is_(None), Alert.snoozed_until <= now),
            )
            .options(selectinload(Alert.jar))
            .order_by(Alert.due_at)
        )
    )


def acknowledge(session: Session, alert: Alert, now: datetime) -> Alert:
    if alert.acknowledged_at is None:
        alert.acknowledged_at = now
    session.flush()
    return alert


def snooze(session: Session, alert: Alert, now: datetime, minutes: int) -> Alert:
    """Hide an alert for a while without pretending it was dealt with."""
    if minutes <= 0:
        raise ValueError("Snooze must be a positive number of minutes")
    alert.snoozed_until = now + timedelta(minutes=minutes)
    session.flush()
    return alert


def acknowledge_for_jar(session: Session, jar_id: int, now: datetime) -> int:
    """Clear every outstanding alert on a jar. Called when it gets fed."""
    outstanding = session.scalars(
        select(Alert).where(
            Alert.jar_id == jar_id,
            Alert.acknowledged_at.is_(None),
            Alert.fired_at.is_not(None),
        )
    )
    count = 0
    for alert in outstanding:
        alert.acknowledged_at = now
        count += 1
    session.flush()
    return count
