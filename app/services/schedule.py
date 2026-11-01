"""When is this jar next due a feed?

Phase 2 turns these into alerts; Phase 1 only needs to show them on a card.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.feeding import Feeding
from app.models.jar import Jar


def last_feeding(session: Session, jar_id: int) -> Feeding | None:
    return session.scalars(
        select(Feeding)
        .where(Feeding.jar_id == jar_id)
        .order_by(Feeding.fed_at.desc(), Feeding.id.desc())
        .limit(1)
    ).first()


def next_due_at(jar: Jar, last_fed_at: datetime | None) -> datetime | None:
    """None when the jar sleeps (dormant/dried) or has never been fed."""
    interval_h = jar.feed_interval_h
    if interval_h is None or last_fed_at is None:
        return None
    return last_fed_at + timedelta(hours=interval_h)


@dataclass(frozen=True)
class FeedStatus:
    last_fed_at: datetime | None
    next_due_at: datetime | None
    is_overdue: bool
    # How far past due, for sorting the dashboard worst-first.
    overdue_by: timedelta | None

    @property
    def never_fed(self) -> bool:
        return self.last_fed_at is None


def feed_status(jar: Jar, last_fed_at: datetime | None, now: datetime) -> FeedStatus:
    due = next_due_at(jar, last_fed_at)
    overdue = due is not None and now >= due
    return FeedStatus(
        last_fed_at=last_fed_at,
        next_due_at=due,
        is_overdue=overdue,
        overdue_by=(now - due) if overdue and due is not None else None,
    )
