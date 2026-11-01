"""Jar lifecycle, the timeline, and the dashboard view model.

Jars are never deleted — archiving keeps the lab-notebook history intact
(CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.base import utcnow
from app.models.enums import JarState
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.jar_state_change import JarStateChange
from app.models.observation import Observation
from app.services import derived
from app.services.schedule import FeedStatus, feed_status, last_feeding

EventKind = Literal["feeding", "observation", "state_change"]


def list_jars(session: Session, *, include_archived: bool = False) -> list[Jar]:
    stmt = select(Jar).order_by(Jar.archived, Jar.is_control, Jar.name)
    if not include_archived:
        stmt = stmt.where(Jar.archived.is_(False))
    return list(session.scalars(stmt))


def get_jar(session: Session, jar_id: int) -> Jar | None:
    return session.scalars(
        select(Jar)
        .where(Jar.id == jar_id)
        .options(selectinload(Jar.parent), selectinload(Jar.children))
    ).first()


def create_jar(session: Session, **fields: Any) -> Jar:
    """Create a jar and open its state history with the state it started in."""
    jar = Jar(**fields)
    session.add(jar)
    session.flush()  # need jar.id for the state change

    session.add(
        JarStateChange(
            jar_id=jar.id,
            from_state=None,  # nothing to come from: the jar is new
            to_state=jar.state,
            changed_at=jar.created_at or utcnow(),
            note="Jar created",
        )
    )
    session.flush()
    return jar


def update_jar(session: Session, jar: Jar, *, state_note: str | None = None, **fields: Any) -> Jar:
    """Apply changes, logging a state change if the state actually moved."""
    previous_state = jar.state

    for key, value in fields.items():
        setattr(jar, key, value)

    new_state = jar.state
    if new_state != previous_state:
        session.add(
            JarStateChange(
                jar_id=jar.id,
                from_state=previous_state,
                to_state=new_state,
                changed_at=utcnow(),
                note=state_note,
            )
        )

    session.flush()
    return jar


def set_state(
    session: Session, jar: Jar, new_state: JarState, note: str | None = None
) -> Jar:
    return update_jar(session, jar, state=new_state, state_note=note)


def set_archived(session: Session, jar: Jar, archived: bool) -> Jar:
    jar.archived = archived
    session.flush()
    return jar


def log_feeding(session: Session, jar: Jar, **fields: Any) -> Feeding:
    feeding = Feeding(jar_id=jar.id, **fields)
    session.add(feeding)
    session.flush()
    return feeding


def log_observation(session: Session, jar: Jar, **fields: Any) -> Observation:
    observation = Observation(jar_id=jar.id, **fields)
    session.add(observation)
    session.flush()
    return observation


def feeding_defaults(session: Session, jar: Jar) -> dict[str, Any]:
    """Pre-fill the 'Fed it' form from this jar's last feeding.

    The common case is feeding the same way as last time, so the form should
    already be correct and take one tap.
    """
    previous = last_feeding(session, jar.id)
    if previous is None:
        return {
            "starter_g": 20.0,
            "flour_g": 40.0,
            "water_g": 40.0,
            "flour_type": jar.flour_type,
            "ambient_temp_c": None,
            "water_temp_c": None,
        }
    return {
        "starter_g": previous.starter_g,
        "flour_g": previous.flour_g,
        "water_g": previous.water_g,
        "flour_type": previous.flour_type or jar.flour_type,
        "ambient_temp_c": previous.ambient_temp_c,
        "water_temp_c": previous.water_temp_c,
    }


@dataclass(frozen=True)
class TimelineEvent:
    kind: EventKind
    at: datetime
    obj: Any
    detail: dict[str, Any]


def timeline(session: Session, jar: Jar) -> list[TimelineEvent]:
    """Feedings, observations and state changes in one list, newest first."""
    events: list[TimelineEvent] = []

    for feeding in session.scalars(
        select(Feeding).where(Feeding.jar_id == jar.id)
    ):
        events.append(
            TimelineEvent(
                kind="feeding",
                at=feeding.fed_at,
                obj=feeding,
                detail=derived.describe_feeding(feeding),
            )
        )

    for observation in session.scalars(
        select(Observation).where(Observation.jar_id == jar.id)
    ):
        events.append(
            TimelineEvent(
                kind="observation",
                at=observation.observed_at,
                obj=observation,
                detail=derived.describe_observation(observation),
            )
        )

    for change in session.scalars(
        select(JarStateChange).where(JarStateChange.jar_id == jar.id)
    ):
        events.append(
            TimelineEvent(
                kind="state_change",
                at=change.changed_at,
                obj=change,
                detail={},
            )
        )

    # Newest first; id as tiebreaker so same-second entries stay stable.
    events.sort(key=lambda e: (e.at, getattr(e.obj, "id", 0)), reverse=True)
    return events


@dataclass(frozen=True)
class JarCard:
    jar: Jar
    status: FeedStatus
    last_feeding: Feeding | None
    last_observation: Observation | None


def jar_card(session: Session, jar: Jar, now: datetime) -> JarCard:
    previous = last_feeding(session, jar.id)
    observation = session.scalars(
        select(Observation)
        .where(Observation.jar_id == jar.id)
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
        .limit(1)
    ).first()
    return JarCard(
        jar=jar,
        status=feed_status(jar, previous.fed_at if previous else None, now),
        last_feeding=previous,
        last_observation=observation,
    )


def dashboard(session: Session, now: datetime) -> list[JarCard]:
    """Active jars, the ones needing attention first."""
    cards = [jar_card(session, jar, now) for jar in list_jars(session)]

    def sort_key(card: JarCard) -> tuple:
        return (
            not card.status.is_overdue,          # overdue first
            card.status.next_due_at is None,     # then jars with a schedule
            card.status.next_due_at or now,      # soonest due next
            card.jar.name.lower(),
        )

    cards.sort(key=sort_key)
    return cards
