"""Seeding reference data into a notebook that already has real work in it.

The safety rules in app/services/seeding.py are the point of this file:
add-only, idempotent, and a dry run that writes nothing.
"""

from __future__ import annotations

from app.models.enums import IngredientRole, JarOrigin, RecipeCategory
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.recipe import EquipmentCycle, EquipmentProgram, Recipe
from app.services import jars as jar_service
from app.services import recipes as recipe_service
from app.services import seeding
from app.services.recipes import IngredientSpec


def a_jar_with_a_feeding(session):
    """What Scott's database actually has in it: one jar, one feeding."""
    jar = jar_service.create_jar(
        session, name="Homemade rye", origin=JarOrigin.HOMEMADE,
        flour_type="whole rye", notes="started from scratch",
    )
    session.commit()
    feeding = jar_service.log_feeding(
        session, jar, starter_g=20, flour_g=40, water_g=40, ambient_temp_c=21.5
    )
    session.commit()
    return jar, feeding


class TestIdempotency:
    def test_running_twice_adds_nothing_the_second_time(self, session):
        first = seeding.seed_all(session)
        session.commit()
        programs = session.query(EquipmentProgram).count()
        cycles = session.query(EquipmentCycle).count()
        recipes = session.query(Recipe).count()

        second = seeding.seed_all(session)
        session.commit()

        assert second.programs_added == []
        assert second.recipes_added == []
        assert len(second.programs_skipped) == len(first.programs_added)
        assert len(second.recipes_skipped) == len(first.recipes_added)
        assert session.query(EquipmentProgram).count() == programs
        assert session.query(EquipmentCycle).count() == cycles
        assert session.query(Recipe).count() == recipes

    def test_a_third_run_is_still_a_no_op(self, session):
        for _ in range(3):
            seeding.seed_all(session)
            session.commit()
        assert session.query(EquipmentProgram).count() == 12
        assert session.query(EquipmentCycle).count() == 28

    def test_a_program_entered_by_hand_is_left_alone(self, session):
        """Scott's own note on his own row must survive a seed run."""
        mine = recipe_service.create_program(
            session,
            name="Basic",
            device="West Bend L5951",
            total_min=999,
            notes="mine, do not touch",
        )
        session.commit()

        seeding.seed_all(session)
        session.commit()

        session.refresh(mine)
        assert mine.total_min == 999
        assert mine.notes == "mine, do not touch"
        assert mine.cycles == [], "no cycles bolted onto an existing row"
        assert session.query(EquipmentProgram).count() == 12, "the other 11 arrived"

    def test_a_recipe_with_the_same_name_but_no_source_is_a_different_recipe(
        self, session
    ):
        """Keyed on name *and* source: his Borodinsky is not the book's."""
        mine = recipe_service.create_recipe(
            session, name="Borodinsky", category=RecipeCategory.RYE,
            ingredients=[IngredientSpec("Rye", IngredientRole.FLOUR, 100.0)],
        )
        session.commit()

        seeding.seed_all(session)
        session.commit()

        session.refresh(mine)
        assert mine.source is None
        assert len(mine.versions) == 1, "no second version written onto it"


class TestItNeverTouchesWhatIsThere:
    def test_the_jar_and_its_feeding_are_untouched(self, session):
        jar, feeding = a_jar_with_a_feeding(session)
        before = (jar.name, jar.flour_type, feeding.flour_g, feeding.water_g)

        seeding.seed_all(session)
        session.commit()

        session.refresh(jar)
        session.refresh(feeding)
        assert (jar.name, jar.flour_type, feeding.flour_g, feeding.water_g) == before

    def test_nothing_is_deleted(self, session):
        jar, feeding = a_jar_with_a_feeding(session)

        seeding.seed_all(session)
        session.commit()

        assert session.get(Jar, jar.id) is not None
        assert session.get(Feeding, feeding.id) is not None
        assert len(jar_service.list_jars(session)) == 1


class TestDryRun:
    def test_it_reports_what_a_real_run_would_add(self, session):
        dry = seeding.seed_all(session, dry_run=True)
        session.rollback()

        assert dry.dry_run is True
        assert len(dry.programs_added) == 12
        assert dry.cycles_added == 28

    def test_it_writes_nothing(self, session):
        seeding.seed_all(session, dry_run=True)
        session.rollback()

        assert session.query(EquipmentProgram).count() == 0
        assert session.query(EquipmentCycle).count() == 0
        assert session.query(Recipe).count() == 0

    def test_it_agrees_with_what_the_real_run_then_does(self, session):
        dry = seeding.seed_all(session, dry_run=True)
        session.rollback()
        real = seeding.seed_all(session)
        session.commit()

        assert dry.programs_added == real.programs_added
        assert dry.recipes_added == real.recipes_added
        assert dry.cycles_added == real.cycles_added

    def test_a_dry_run_after_a_real_one_reports_nothing_to_do(self, session):
        seeding.seed_all(session)
        session.commit()

        dry = seeding.seed_all(session, dry_run=True)
        session.rollback()
        assert dry.added_anything is False


class TestTheReport:
    def test_it_reads_as_something_a_person_would_want_to_see(self, session):
        report = seeding.seed_all(session)
        session.commit()
        text = "\n".join(report.lines())
        assert "Added 12 programs (28 cycle rows)" in text
        assert "West Bend L5951 — 1. Basic" in text

    def test_a_dry_run_says_would(self, session):
        report = seeding.seed_all(session, dry_run=True)
        session.rollback()
        assert "Would add" in report.lines()[0]


class TestTheCommandLine:
    def test_dry_run_changes_nothing(self, session, capsys):
        from app import seed as seed_cli

        assert seed_cli.main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "Dry run: nothing was written." in out
        assert session.query(EquipmentProgram).count() == 0

    def test_a_real_run_seeds(self, session, capsys):
        from app import seed as seed_cli

        assert seed_cli.main([]) == 0
        assert "Added 12 programs" in capsys.readouterr().out
        assert session.query(EquipmentProgram).count() == 12
