"""When a jar is next due a feed. Phase 2 turns these into alerts."""

from __future__ import annotations

from datetime import timedelta

from app.models.enums import JarOrigin, JarState
from app.models.jar import Jar
from app.services.schedule import feed_status, next_due_at


def _jar(state: JarState = JarState.ACTIVE, room_h: int = 12, fridge_h: int = 168) -> Jar:
    return Jar(
        name="Rye",
        origin=JarOrigin.HOMEMADE,
        state=state,
        feed_interval_room_h=room_h,
        feed_interval_fridge_h=fridge_h,
    )


def test_active_jars_use_the_room_interval(frozen_now):
    jar = _jar(JarState.ACTIVE, room_h=12)

    assert next_due_at(jar, frozen_now) == frozen_now + timedelta(hours=12)


def test_fridge_jars_use_the_fridge_interval(frozen_now):
    jar = _jar(JarState.FRIDGE, fridge_h=168)

    assert next_due_at(jar, frozen_now) == frozen_now + timedelta(hours=168)


def test_sleeping_jars_are_never_due(frozen_now):
    for state in (JarState.DORMANT, JarState.DRIED):
        assert next_due_at(_jar(state), frozen_now) is None
        assert _jar(state).feed_interval_h is None


def test_a_jar_that_has_never_been_fed_has_no_due_date(frozen_now):
    assert next_due_at(_jar(), None) is None


def test_status_flags_an_overdue_jar(frozen_now):
    fed_at = frozen_now - timedelta(hours=20)  # interval is 12h

    status = feed_status(_jar(room_h=12), fed_at, frozen_now)

    assert status.is_overdue
    assert status.overdue_by == timedelta(hours=8)


def test_status_is_not_overdue_before_the_interval_elapses(frozen_now):
    status = feed_status(_jar(room_h=12), frozen_now - timedelta(hours=3), frozen_now)

    assert not status.is_overdue
    assert status.overdue_by is None
    assert status.next_due_at == frozen_now + timedelta(hours=9)


def test_due_exactly_now_counts_as_overdue(frozen_now):
    # Boundary: a jar due this very second should prompt, not wait.
    status = feed_status(_jar(room_h=12), frozen_now - timedelta(hours=12), frozen_now)

    assert status.is_overdue


def test_never_fed_is_reported_distinctly(frozen_now):
    status = feed_status(_jar(), None, frozen_now)

    assert status.never_fed
    assert not status.is_overdue
