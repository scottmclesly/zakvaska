"""Alert lifecycle.

Phase 2's acceptance check in docs/dev/TODO-v1.md: an alert fires, snooze delays
it, a feeding clears it, and a restart mid-countdown still fires.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.alert import Alert
from app.models.enums import JarOrigin, JarState
from app.services import alerts as alert_service
from app.services import jars as jar_service


def make_jar(session, *, state=JarState.ACTIVE, interval_h=12, **kw):
    return jar_service.create_jar(
        session, name=kw.pop("name", "Rye"), origin=JarOrigin.HOMEMADE,
        state=state, feed_interval_room_h=interval_h, **kw,
    )


def feed(session, jar, when, **kw):
    return jar_service.log_feeding(
        session, jar, fed_at=when, starter_g=20, flour_g=40, water_g=40, **kw
    )


def all_alerts(session) -> list[Alert]:
    return list(session.scalars(select(Alert)))


class TestReconcile:
    def test_creates_a_pending_alert_for_the_next_feed(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=1))

        alert_service.reconcile(session, frozen_now)

        alerts = all_alerts(session)
        assert len(alerts) == 1
        assert alerts[0].due_at == frozen_now + timedelta(hours=11)
        assert alerts[0].is_pending, "not due yet, so it should not have fired"

    def test_fires_once_the_due_moment_passes(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))  # 12h interval

        result = alert_service.reconcile(session, frozen_now)

        assert len(result.fired) == 1
        assert result.fired[0].fired_at == frozen_now
        assert alert_service.showing(session, frozen_now)

    def test_is_idempotent(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))

        first = alert_service.reconcile(session, frozen_now)
        second = alert_service.reconcile(session, frozen_now)
        third = alert_service.reconcile(session, frozen_now + timedelta(minutes=5))

        assert len(first.fired) == 1
        assert not second.fired, "must not fire the same alert twice"
        assert not third.fired
        assert len(all_alerts(session)) == 1, "and must not pile up rows"

    @pytest.mark.parametrize("state", [JarState.DORMANT, JarState.DRIED])
    def test_sleeping_jars_are_never_alerted(self, session, frozen_now, state):
        jar = make_jar(session, state=state)
        feed(session, jar, frozen_now - timedelta(days=30))

        alert_service.reconcile(session, frozen_now)

        assert all_alerts(session) == []

    def test_archived_jars_are_never_alerted(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        jar_service.set_archived(session, jar, True)

        alert_service.reconcile(session, frozen_now)

        assert all_alerts(session) == []

    def test_a_jar_that_has_never_been_fed_raises_nothing(self, session, frozen_now):
        make_jar(session)

        alert_service.reconcile(session, frozen_now)

        assert all_alerts(session) == []

    def test_moving_a_jar_to_dormant_withdraws_its_pending_alert(
        self, session, frozen_now
    ):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=1))
        alert_service.reconcile(session, frozen_now)
        assert len(all_alerts(session)) == 1

        jar_service.set_state(session, jar, JarState.DORMANT)
        alert_service.reconcile(session, frozen_now)

        assert all_alerts(session) == [], "a sleeping jar should stop nagging"

    def test_feeding_early_withdraws_the_old_prediction(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=6))
        alert_service.reconcile(session, frozen_now)
        original_due = all_alerts(session)[0].due_at

        feed(session, jar, frozen_now)  # fed early
        alert_service.reconcile(session, frozen_now)

        alerts = all_alerts(session)
        assert len(alerts) == 1, "the stale pending alert should be gone"
        assert alerts[0].due_at != original_due
        assert alerts[0].due_at == frozen_now + timedelta(hours=12)

    def test_a_fired_alert_is_never_silently_withdrawn(self, session, frozen_now):
        # Pending alerts are predictions and can be dropped; a fired one
        # actually happened, so it must survive until acknowledged.
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        jar_service.set_state(session, jar, JarState.DORMANT)

        alert_service.reconcile(session, frozen_now)

        assert len(all_alerts(session)) == 1
        assert all_alerts(session)[0].fired_at is not None


class TestRestartSafety:
    """The acceptance check: restart mid-countdown still fires."""

    def test_an_alert_due_while_the_process_was_down_fires_on_the_next_pass(
        self, session, frozen_now
    ):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=1))
        alert_service.reconcile(session, frozen_now)  # pending, due in 11h
        assert not alert_service.showing(session, frozen_now)

        # ... process dies here, comes back up 12 hours later ...
        session.expunge_all()
        later = frozen_now + timedelta(hours=12)

        result = alert_service.reconcile(session, later)

        assert len(result.fired) == 1
        assert alert_service.showing(session, later)

    def test_nothing_is_lost_when_the_alert_row_was_never_written(
        self, session, frozen_now
    ):
        # Process never got a tick in before dying: no alert row at all.
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        assert all_alerts(session) == []

        result = alert_service.reconcile(session, frozen_now)

        assert len(result.fired) == 1, "state is rebuilt from jars, not memory"

    def test_reconcile_does_not_re_fire_an_alert_across_a_restart(
        self, session, frozen_now
    ):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        session.commit()
        session.expunge_all()

        result = alert_service.reconcile(session, frozen_now + timedelta(minutes=1))

        assert not result.fired


class TestSnooze:
    def test_snoozing_hides_the_alert_for_a_while(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert = alert_service.showing(session, frozen_now)[0]

        alert_service.snooze(session, alert, frozen_now, minutes=30)

        assert not alert_service.showing(session, frozen_now)
        assert not alert_service.showing(session, frozen_now + timedelta(minutes=29))

    def test_it_comes_back_when_the_snooze_runs_out(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert_service.snooze(
            session, alert_service.showing(session, frozen_now)[0],
            frozen_now, minutes=30,
        )

        later = frozen_now + timedelta(minutes=31)

        assert alert_service.showing(session, later)

    def test_snoozing_does_not_create_a_duplicate(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert_service.snooze(
            session, alert_service.showing(session, frozen_now)[0],
            frozen_now, minutes=30,
        )

        alert_service.reconcile(session, frozen_now + timedelta(minutes=5))

        assert len(all_alerts(session)) == 1

    @pytest.mark.parametrize("minutes", [0, -10])
    def test_a_nonsense_snooze_is_refused(self, session, frozen_now, minutes):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert = alert_service.showing(session, frozen_now)[0]

        with pytest.raises(ValueError, match="positive"):
            alert_service.snooze(session, alert, frozen_now, minutes=minutes)


class TestAcknowledge:
    def test_acknowledging_removes_it_for_good(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert = alert_service.showing(session, frozen_now)[0]

        alert_service.acknowledge(session, alert, frozen_now)

        assert not alert_service.showing(session, frozen_now)
        assert not alert_service.showing(session, frozen_now + timedelta(days=1))

    def test_feeding_the_jar_clears_its_alert(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        assert alert_service.showing(session, frozen_now)

        feed(session, jar, frozen_now)  # the actual answer to the alert

        assert not alert_service.showing(session, frozen_now)

    def test_feeding_one_jar_leaves_the_others_alone(self, session, frozen_now):
        mine = make_jar(session, name="Mine")
        control = make_jar(session, name="Control")
        for jar in (mine, control):
            feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        assert len(alert_service.showing(session, frozen_now)) == 2

        feed(session, mine, frozen_now)

        remaining = alert_service.showing(session, frozen_now)
        assert [a.jar.name for a in remaining] == ["Control"]

    def test_acknowledging_twice_keeps_the_first_time(self, session, frozen_now):
        jar = make_jar(session)
        feed(session, jar, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)
        alert = alert_service.showing(session, frozen_now)[0]

        alert_service.acknowledge(session, alert, frozen_now)
        alert_service.acknowledge(session, alert, frozen_now + timedelta(hours=1))

        assert alert.acknowledged_at == frozen_now


class TestShowingOrder:
    def test_the_most_overdue_jar_comes_first(self, session, frozen_now):
        early = make_jar(session, name="Worst")
        late = make_jar(session, name="Less bad")
        feed(session, early, frozen_now - timedelta(hours=40))
        feed(session, late, frozen_now - timedelta(hours=20))
        alert_service.reconcile(session, frozen_now)

        showing = alert_service.showing(session, frozen_now)

        assert [a.jar.name for a in showing] == ["Worst", "Less bad"]
