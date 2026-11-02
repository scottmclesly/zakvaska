"""Starting a bake, running it, and writing up the result."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.enums import (
    BakeMethod,
    BakeStatus,
    IngredientRole,
    JarOrigin,
    RecipeCategory,
)
from app.services import bakes as bake_service
from app.services import jars as jar_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec


def make_recipe(session, *, name="Borodinsky"):
    recipe = recipe_service.create_recipe(
        session,
        name=name,
        category=RecipeCategory.RYE,
        ingredients=[
            IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
            IngredientSpec("Rye levain", IngredientRole.LEVAIN, 30.0),
            IngredientSpec("Salt", IngredientRole.SALT, 2.0),
        ],
        stages=[
            StageSpec("scald (zavarka)", duration_min=240, temp_c=65.0),
            StageSpec("sponge", duration_min=240),
            StageSpec("final dough", duration_min=30),
            StageSpec("proof", duration_min=120),
            StageSpec("bake", duration_min=60, temp_c=200.0),
        ],
    )
    session.commit()
    return recipe


def make_jar(session, *, name="Homemade rye", control=False):
    jar = jar_service.create_jar(
        session,
        name=name,
        origin=JarOrigin.PURCHASED if control else JarOrigin.HOMEMADE,
        is_control=control,
    )
    session.commit()
    return jar


class TestStartingABake:
    def test_the_stages_are_copied_in_as_the_plan(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        assert [log.name for log in bake.stage_logs] == [
            "scald (zavarka)", "sponge", "final dough", "proof", "bake",
        ]
        assert [log.planned_min for log in bake.stage_logs] == [
            240, 240, 30, 120, 60
        ]
        assert bake.stage_logs[0].planned_temp_c == 65.0

    def test_editing_the_recipe_afterwards_leaves_the_bake_alone(self, session):
        """The plan is a copy, which is the whole reason it is a copy."""
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        recipe_service.add_version(
            session, recipe,
            ingredients=[IngredientSpec("Rye", IngredientRole.FLOUR, 100.0)],
            stages=[StageSpec("bake", duration_min=90)],
        )
        session.commit()

        assert len(bake.stage_logs) == 5
        assert bake.stage_logs[0].name == "scald (zavarka)"
        assert bake.version.version == 1

    def test_it_starts_planned_with_nothing_logged(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        assert bake.status is BakeStatus.PLANNED
        assert bake.started_at is None
        assert all(log.actual_start is None for log in bake.stage_logs)

    def test_it_can_be_started_there_and_then(self, session, frozen_now):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(
            session, recipe.latest_version,
            started_at=frozen_now, status=BakeStatus.IN_PROGRESS,
        )
        session.commit()
        assert bake.started_at == frozen_now
        assert bake.status is BakeStatus.IN_PROGRESS

    def test_it_records_the_jar_method_and_machine(self, session):
        recipe = make_recipe(session)
        jar = make_jar(session)
        program = recipe_service.create_program(
            session, name="Whole Wheat", device="West Bend 41300", total_min=230
        )
        session.commit()

        bake = bake_service.start_bake(
            session, recipe.latest_version,
            method=BakeMethod.BREAD_MAKER,
            jar_id=jar.id,
            equipment_program_id=program.id,
            crust_setting="dark",
            loaf_size="2 lb",
            total_flour_g=500,
        )
        session.commit()

        assert bake.jar.name == "Homemade rye"
        assert bake.method is BakeMethod.BREAD_MAKER
        assert bake.program.name == "Whole Wheat"
        assert bake.crust_setting == "dark"

    def test_the_grams_come_from_the_flour_total(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(
            session, recipe.latest_version, total_flour_g=500
        )
        session.commit()

        scaled = bake_service.scaled(bake)
        assert [line.grams for line in scaled.ingredients] == [
            500.0, 400.0, 150.0, 10.0
        ]

    def test_no_flour_total_means_no_grams(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()
        assert bake_service.scaled(bake) is None


class TestRunningIt:
    def _bake(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(
            session, recipe.latest_version, total_flour_g=500
        )
        session.commit()
        return bake

    def test_starting_a_stage_starts_the_bake(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.start_stage(session, bake, bake.stage_logs[0], frozen_now)
        session.commit()

        assert bake.status is BakeStatus.IN_PROGRESS
        assert bake.started_at == frozen_now
        assert bake.stage_logs[0].is_running

    def test_a_second_stage_does_not_move_the_bake_start(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.start_stage(session, bake, bake.stage_logs[0], frozen_now)
        later = frozen_now + timedelta(hours=4)
        bake_service.end_stage(session, bake, bake.stage_logs[0], later)
        bake_service.start_stage(session, bake, bake.stage_logs[1], later)
        session.commit()

        assert bake.started_at == frozen_now

    def test_ending_a_stage_records_how_long_it_took(self, session, frozen_now):
        bake = self._bake(session)
        log = bake.stage_logs[0]
        bake_service.start_stage(session, bake, log, frozen_now)
        bake_service.end_stage(
            session, bake, log, frozen_now + timedelta(minutes=300)
        )
        session.commit()

        assert log.is_done
        assert log.actual_min == 300
        # Planned 240, so it ran an hour long.
        assert log.drift_min == 60

    def test_drift_needs_both_numbers(self, session, frozen_now):
        bake = self._bake(session)
        log = bake.stage_logs[0]
        assert log.drift_min is None  # nothing logged yet
        bake_service.start_stage(session, bake, log, frozen_now)
        session.commit()
        assert log.actual_min is None

    def test_ending_a_stage_nobody_started_still_records_it(
        self, session, frozen_now
    ):
        bake = self._bake(session)
        log = bake.stage_logs[2]
        bake_service.end_stage(session, bake, log, frozen_now)
        session.commit()

        assert log.is_done
        assert log.actual_start == frozen_now
        assert log.actual_min == 0

    def test_undo_clears_a_mistaken_tap(self, session, frozen_now):
        bake = self._bake(session)
        log = bake.stage_logs[0]
        bake_service.start_stage(session, bake, log, frozen_now)
        bake_service.clear_stage(session, log)
        session.commit()

        assert log.actual_start is None
        assert not log.is_running

    def test_progress_tracks_what_is_running_and_what_is_next(
        self, session, frozen_now
    ):
        bake = self._bake(session)
        bake_service.start_stage(session, bake, bake.stage_logs[0], frozen_now)
        bake_service.end_stage(
            session, bake, bake.stage_logs[0], frozen_now + timedelta(hours=4)
        )
        bake_service.start_stage(
            session, bake, bake.stage_logs[1], frozen_now + timedelta(hours=4)
        )
        session.commit()

        progress = bake_service.progress(bake)
        assert progress.done == 1
        assert progress.total == 5
        assert progress.running.name == "sponge"
        assert progress.next_up.name == "final dough"
        assert not progress.is_complete

    def test_progress_is_complete_when_every_stage_is_done(
        self, session, frozen_now
    ):
        bake = self._bake(session)
        for index, log in enumerate(bake.stage_logs):
            when = frozen_now + timedelta(hours=index)
            bake_service.start_stage(session, bake, log, when)
            bake_service.end_stage(session, bake, log, when + timedelta(minutes=30))
        session.commit()

        assert bake_service.progress(bake).is_complete

    def test_planned_total_adds_the_stages_up(self, session):
        bake = self._bake(session)
        assert bake_service.planned_total_min(bake) == 690

    def test_elapsed_runs_to_now_until_it_finishes(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.start_stage(session, bake, bake.stage_logs[0], frozen_now)
        session.commit()

        now = frozen_now + timedelta(minutes=90)
        assert bake_service.elapsed_min(bake, now) == 90

        bake_service.finish_bake(session, bake, frozen_now + timedelta(minutes=120))
        session.commit()
        # Finished, so "now" no longer moves it.
        assert bake_service.elapsed_min(bake, now + timedelta(days=1)) == 120

    def test_finishing_sets_the_status(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.finish_bake(session, bake, frozen_now)
        session.commit()
        assert bake.status is BakeStatus.DONE
        assert bake.finished_at == frozen_now

    def test_a_failed_bake_is_still_a_record(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.finish_bake(
            session, bake, frozen_now, status=BakeStatus.FAILED
        )
        session.commit()
        assert bake.status is BakeStatus.FAILED
        assert bake.status.is_finished

    def test_reopening_puts_it_back_in_progress(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.finish_bake(session, bake, frozen_now)
        bake_service.reopen_bake(session, bake)
        session.commit()
        assert bake.status is BakeStatus.IN_PROGRESS
        assert bake.finished_at is None


class TestResults:
    def _bake(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()
        return bake

    def test_saving_a_result_finishes_the_bake(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.save_result(
            session, bake, rating=4, crust="thick", next_time="less water",
            now=frozen_now,
        )
        session.commit()

        assert bake.result.rating == 4
        assert bake.status is BakeStatus.DONE
        assert bake.finished_at == frozen_now

    def test_saving_again_replaces_rather_than_duplicating(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.save_result(session, bake, rating=2, now=frozen_now)
        session.commit()
        bake_service.save_result(
            session, bake, rating=5, taste="malty", now=frozen_now
        )
        session.commit()

        assert bake.result.rating == 5
        assert bake.result.taste == "malty"
        from app.models.bake import BakeResult
        assert session.query(BakeResult).count() == 1

    def test_a_result_does_not_un_fail_a_bake(self, session, frozen_now):
        bake = self._bake(session)
        bake_service.finish_bake(
            session, bake, frozen_now, status=BakeStatus.FAILED
        )
        bake_service.save_result(
            session, bake, rating=1, next_time="do not do that again",
            now=frozen_now,
        )
        session.commit()
        assert bake.status is BakeStatus.FAILED


class TestTheList:
    def _two_recipes(self, session):
        borodinsky = make_recipe(session)
        sourdough = make_recipe(session, name="Plain sourdough")
        homemade = make_jar(session)
        control = make_jar(session, name="Soviet culture", control=True)
        return borodinsky, sourdough, homemade, control

    def test_newest_first(self, session):
        recipe = make_recipe(session)
        first = bake_service.start_bake(session, recipe.latest_version)
        second = bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        found = bake_service.list_bakes(session)
        assert [b.id for b in found] == [second.id, first.id]

    def test_filter_by_recipe_spans_its_versions(self, session):
        borodinsky, sourdough, _, _ = self._two_recipes(session)
        bake_service.start_bake(session, borodinsky.latest_version)
        v2 = recipe_service.add_version(
            session, borodinsky,
            ingredients=[IngredientSpec("Rye", IngredientRole.FLOUR, 100.0)],
            stages=[],
        )
        bake_service.start_bake(session, v2)
        bake_service.start_bake(session, sourdough.latest_version)
        session.commit()

        found = bake_service.list_bakes(session, recipe_id=borodinsky.id)
        assert len(found) == 2
        assert {b.version.version for b in found} == {1, 2}

    def test_filter_by_jar(self, session):
        recipe, _, homemade, control = self._two_recipes(session)
        bake_service.start_bake(session, recipe.latest_version, jar_id=homemade.id)
        bake_service.start_bake(session, recipe.latest_version, jar_id=control.id)
        bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        found = bake_service.list_bakes(session, jar_id=control.id)
        assert [b.jar.name for b in found] == ["Soviet culture"]

    def test_filter_by_rating_drops_the_unrated(self, session, frozen_now):
        recipe = make_recipe(session)
        good = bake_service.start_bake(session, recipe.latest_version)
        poor = bake_service.start_bake(session, recipe.latest_version)
        bake_service.start_bake(session, recipe.latest_version)  # unrated
        bake_service.save_result(session, good, rating=5, now=frozen_now)
        bake_service.save_result(session, poor, rating=2, now=frozen_now)
        session.commit()

        found = bake_service.list_bakes(session, min_rating=4)
        assert [b.id for b in found] == [good.id]

    def test_filter_by_status(self, session, frozen_now):
        recipe = make_recipe(session)
        planned = bake_service.start_bake(session, recipe.latest_version)
        running = bake_service.start_bake(session, recipe.latest_version)
        bake_service.start_stage(session, running, running.stage_logs[0], frozen_now)
        session.commit()

        assert [b.id for b in bake_service.list_bakes(
            session, status=BakeStatus.PLANNED
        )] == [planned.id]
        assert [b.id for b in bake_service.list_bakes(
            session, status=BakeStatus.IN_PROGRESS
        )] == [running.id]

    def test_filters_stack(self, session, frozen_now):
        recipe, other, homemade, control = self._two_recipes(session)
        wanted = bake_service.start_bake(
            session, recipe.latest_version, jar_id=control.id
        )
        bake_service.start_bake(session, recipe.latest_version, jar_id=homemade.id)
        bake_service.start_bake(session, other.latest_version, jar_id=control.id)
        bake_service.save_result(session, wanted, rating=5, now=frozen_now)
        session.commit()

        found = bake_service.list_bakes(
            session, recipe_id=recipe.id, jar_id=control.id, min_rating=4
        )
        assert [b.id for b in found] == [wanted.id]

    def test_archived_bakes_are_hidden_but_kept(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        bake_service.set_archived(session, bake, True)
        session.commit()

        assert bake_service.list_bakes(session) == []
        assert len(bake_service.list_bakes(session, include_archived=True)) == 1
        assert bake_service.get_bake(session, bake.id) is not None


class TestItShowsUpWhereItShould:
    def test_on_its_recipe_version(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()

        version = recipe_service.get_version(session, recipe.id, 1)
        assert [b.id for b in version.bakes] == [bake.id]

    def test_on_its_jar(self, session):
        recipe = make_recipe(session)
        jar = make_jar(session)
        bake = bake_service.start_bake(
            session, recipe.latest_version, jar_id=jar.id
        )
        session.commit()

        assert [b.id for b in jar_service.get_jar(session, jar.id).bakes] == [bake.id]

    def test_archiving_a_jar_does_not_touch_its_bakes(self, session):
        recipe = make_recipe(session)
        jar = make_jar(session)
        bake = bake_service.start_bake(
            session, recipe.latest_version, jar_id=jar.id
        )
        jar_service.set_archived(session, jar, True)
        session.commit()

        assert bake_service.get_bake(session, bake.id).jar_id == jar.id


class TestLabels:
    def test_a_bake_names_its_recipe_and_version(self, session):
        recipe = make_recipe(session)
        bake = bake_service.start_bake(session, recipe.latest_version)
        session.commit()
        assert bake.label == "Borodinsky v1"

    def test_method_labels_read_as_english(self):
        assert BakeMethod.DUTCH_OVEN.label == "Cast-iron pot"
        assert BakeMethod.BREAD_MAKER.uses_program
        assert not BakeMethod.OVEN.uses_program

    def test_only_finished_statuses_count_as_finished(self):
        assert BakeStatus.DONE.is_finished
        assert BakeStatus.FAILED.is_finished
        assert not BakeStatus.PLANNED.is_finished
        assert not BakeStatus.IN_PROGRESS.is_finished
