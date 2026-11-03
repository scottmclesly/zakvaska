"""Jar lifecycle: state history, archiving, timeline, dashboard ordering."""

from __future__ import annotations

from datetime import timedelta

from app.models.enums import BubbleLevel, JarOrigin, JarState
from app.models.jar import Jar
from app.services import jars as jar_service


def _make(session, name="Rye", **kw) -> Jar:
    fields = {"name": name, "origin": JarOrigin.HOMEMADE, "state": JarState.ACTIVE}
    fields.update(kw)
    return jar_service.create_jar(session, **fields)


def test_creating_a_jar_opens_its_state_history(session):
    jar = _make(session)
    session.commit()

    changes = jar.state_changes
    assert len(changes) == 1
    assert changes[0].from_state is None  # nothing to come from
    assert changes[0].to_state is JarState.ACTIVE


def test_moving_a_jar_logs_the_transition(session):
    jar = _make(session)
    jar_service.set_state(session, jar, JarState.FRIDGE, "Going away for a week")
    session.commit()

    latest = jar.state_changes[0]
    assert latest.from_state is JarState.ACTIVE
    assert latest.to_state is JarState.FRIDGE
    assert latest.note == "Going away for a week"


def test_an_edit_that_does_not_move_the_state_logs_nothing(session):
    jar = _make(session)
    jar_service.update_jar(session, jar, name="Renamed", state=JarState.ACTIVE)
    session.commit()

    assert len(jar.state_changes) == 1  # just the creation entry
    assert jar.name == "Renamed"


def test_archiving_keeps_the_jar_and_its_history(session):
    jar = _make(session)
    jar_service.log_feeding(session, jar, starter_g=20, flour_g=40, water_g=40)
    jar_service.set_archived(session, jar, True)
    session.commit()

    assert session.get(Jar, jar.id) is not None, "jars are archived, never deleted"
    assert jar.archived
    assert len(jar.feedings) == 1


def test_archived_jars_are_hidden_from_the_default_listing(session):
    kept = _make(session, "Kept")
    gone = _make(session, "Archived")
    jar_service.set_archived(session, gone, True)
    session.commit()

    assert [j.name for j in jar_service.list_jars(session)] == ["Kept"]
    names = {j.name for j in jar_service.list_jars(session, include_archived=True)}
    assert names == {"Kept", "Archived"}


def test_lineage_links_parent_and_child(session):
    parent = _make(session, "Mother")
    child = _make(session, "Split", parent_jar_id=parent.id)
    session.commit()

    assert child.parent.name == "Mother"
    assert [c.name for c in parent.children] == ["Split"]


class TestTimeline:
    def test_merges_every_event_newest_first(self, session):
        jar = _make(session)
        # State changes are stamped with the real clock, so the other events
        # are placed relative to the jar's own creation rather than a frozen
        # instant — otherwise the two time bases disagree.
        created = jar.created_at
        jar_service.set_state(session, jar, JarState.FRIDGE)
        jar_service.log_feeding(
            session, jar, fed_at=created + timedelta(hours=1),
            starter_g=20, flour_g=40, water_g=40,
        )
        jar_service.log_observation(
            session, jar, observed_at=created + timedelta(hours=2),
            start_height_mm=20, height_mm=50, bubbles=BubbleLevel.MANY,
        )
        session.commit()

        events = jar_service.timeline(session, jar)

        assert [e.kind for e in events] == [
            "observation",    # created + 2h
            "feeding",        # created + 1h
            "state_change",   # moved to the fridge
            "state_change",   # creation, oldest
        ]
        assert [e.at for e in events] == sorted(
            (e.at for e in events), reverse=True
        )
        assert events[-1].obj.from_state is None, "creation entry sits at the bottom"

    def test_carries_the_derived_values(self, session):
        jar = _make(session)
        jar_service.log_feeding(session, jar, starter_g=20, flour_g=40, water_g=40)
        jar_service.log_observation(session, jar, start_height_mm=20, height_mm=50)
        session.commit()

        by_kind = {e.kind: e.detail for e in jar_service.timeline(session, jar)}

        assert by_kind["feeding"]["ratio"] == "1:2:2"
        assert by_kind["feeding"]["hydration_pct"] == 100.0
        assert by_kind["feeding"]["total_g"] == 100.0
        assert by_kind["observation"]["rise_pct"] == 150.0


class TestFeedingDefaults:
    def test_first_feeding_gets_a_sensible_starting_point(self, session):
        jar = _make(session, flour_type="whole rye")
        session.commit()

        defaults = jar_service.feeding_defaults(session, jar)

        assert defaults["starter_g"] == 20.0
        assert defaults["flour_type"] == "whole rye"

    def test_later_feedings_copy_the_last_one(self, session):
        jar = _make(session)
        jar_service.log_feeding(
            session, jar, starter_g=35, flour_g=70, water_g=85,
            flour_type="dark rye", ambient_temp_c=21.0,
        )
        session.commit()

        defaults = jar_service.feeding_defaults(session, jar)

        # One tap to repeat the last feeding is the whole point of this form.
        assert defaults["starter_g"] == 35
        assert defaults["flour_g"] == 70
        assert defaults["water_g"] == 85
        assert defaults["flour_type"] == "dark rye"
        assert defaults["ambient_temp_c"] == 21.0


class TestDashboardOrdering:
    def test_overdue_jars_come_first(self, session, frozen_now):
        fine = _make(session, "Fine")
        late = _make(session, "Late")
        jar_service.log_feeding(
            session, fine, fed_at=frozen_now - timedelta(hours=1),
            starter_g=20, flour_g=40, water_g=40,
        )
        jar_service.log_feeding(
            session, late, fed_at=frozen_now - timedelta(hours=30),
            starter_g=20, flour_g=40, water_g=40,
        )
        session.commit()

        cards = jar_service.dashboard(session, frozen_now)

        assert [c.jar.name for c in cards] == ["Late", "Fine"]
        assert cards[0].status.is_overdue

    def test_unfed_jars_sort_after_scheduled_ones(self, session, frozen_now):
        scheduled = _make(session, "Scheduled")
        never = _make(session, "Never fed")
        jar_service.log_feeding(
            session, scheduled, fed_at=frozen_now - timedelta(hours=1),
            starter_g=20, flour_g=40, water_g=40,
        )
        session.commit()

        cards = jar_service.dashboard(session, frozen_now)

        assert [c.jar.name for c in cards] == ["Scheduled", "Never fed"]


class TestRiseSeries:
    def test_measurements_come_back_oldest_first(self, session, frozen_now):
        jar = _make(session)
        for hours, height in ((2, 60.0), (10, 40.0), (6, 50.0)):
            jar_service.log_observation(
                session, jar, observed_at=frozen_now - timedelta(hours=hours),
                start_height_mm=40.0, height_mm=height,
            )
        session.commit()

        (series,) = jar_service.rise_series(session, [jar])

        assert [round(s.value) for s in series.samples] == [0, 25, 50]

    def test_an_observation_with_no_ruler_against_it_is_skipped(
        self, session, frozen_now
    ):
        jar = _make(session)
        jar_service.log_observation(
            session, jar, observed_at=frozen_now, bubbles=BubbleLevel.MANY
        )
        jar_service.log_observation(
            session, jar, observed_at=frozen_now,
            start_height_mm=40.0, height_mm=80.0,
        )
        session.commit()

        (series,) = jar_service.rise_series(session, [jar])

        assert [s.value for s in series.samples] == [100.0]

    def test_a_jar_nobody_has_measured_gets_no_line_at_all(
        self, session, frozen_now
    ):
        """An empty line in the key reads as a jar that failed."""
        measured = _make(session, "Measured")
        never = _make(session, "Never measured")
        jar_service.log_observation(
            session, measured, observed_at=frozen_now,
            start_height_mm=40.0, height_mm=80.0,
        )
        session.commit()

        series = jar_service.rise_series(session, [measured, never])

        assert [s.name for s in series] == ["Measured"]

    def test_the_control_is_carried_through_to_the_plot(self, session, frozen_now):
        jar = _make(session, "Soviet", is_control=True)
        jar_service.log_observation(
            session, jar, observed_at=frozen_now,
            start_height_mm=40.0, height_mm=80.0,
        )
        session.commit()

        (series,) = jar_service.rise_series(session, [jar])

        assert series.is_control

    def test_asking_about_no_jars_asks_the_database_nothing(self, session):
        assert jar_service.rise_series(session, []) == []
