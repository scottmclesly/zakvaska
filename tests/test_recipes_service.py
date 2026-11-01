"""Recipe versioning and the version diff."""

from __future__ import annotations

from app.models.enums import IngredientRole, RecipeCategory
from app.services import recipes as recipe_service
from app.services.recipe_diff import diff_versions
from app.services.recipes import IngredientSpec, StageSpec


def rye() -> list[IngredientSpec]:
    return [
        IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
        IngredientSpec("Water", IngredientRole.WATER, 80.0),
        IngredientSpec("Rye levain", IngredientRole.LEVAIN, 30.0),
        IngredientSpec("Red rye malt", IngredientRole.OTHER, 5.0),
        IngredientSpec("Salt", IngredientRole.SALT, 2.0),
    ]


def stages() -> list[StageSpec]:
    return [
        StageSpec("scald (zavarka)", duration_min=240, temp_c=65.0),
        StageSpec("sponge", duration_min=240, temp_c=29.0),
        StageSpec("final dough", duration_min=30),
        StageSpec("proof", duration_min=120, temp_c=28.0),
        StageSpec("bake", duration_min=60, temp_c=200.0),
    ]


def make(session, **over):
    recipe = recipe_service.create_recipe(
        session,
        name=over.get("name", "Borodinsky"),
        category=over.get("category", RecipeCategory.RYE),
        ingredients=over.get("ingredients", rye()),
        stages=over.get("stages", stages()),
        notes=over.get("notes", "first attempt"),
    )
    session.commit()
    return recipe


class TestCreate:
    def test_a_new_recipe_starts_at_version_one(self, session):
        recipe = make(session)
        assert len(recipe.versions) == 1
        assert recipe.latest_version.version == 1
        assert recipe.latest_version.label == "v1"

    def test_ingredients_keep_the_order_they_were_entered(self, session):
        recipe = make(session)
        version = recipe.latest_version
        assert [i.name for i in version.ingredients] == [
            s.name for s in rye()
        ]
        assert [i.seq for i in version.ingredients] == [0, 1, 2, 3, 4]

    def test_stages_keep_their_order(self, session):
        recipe = make(session)
        assert [s.name for s in recipe.latest_version.stages] == [
            "scald (zavarka)", "sponge", "final dough", "proof", "bake",
        ]

    def test_the_note_belongs_to_the_version(self, session):
        recipe = make(session)
        assert recipe.latest_version.notes == "first attempt"


class TestVersioning:
    def test_an_edit_writes_a_new_version(self, session):
        recipe = make(session)
        changed = rye()
        changed[3].baker_pct = 8.0

        recipe_service.add_version(
            session, recipe,
            ingredients=changed, stages=stages(), notes="more malt",
        )
        session.commit()

        assert [v.version for v in recipe.versions] == [2, 1]
        assert recipe.latest_version.version == 2

    def test_the_old_version_is_untouched(self, session):
        recipe = make(session)
        changed = rye()
        changed[3].baker_pct = 8.0
        recipe_service.add_version(
            session, recipe, ingredients=changed, stages=stages()
        )
        session.commit()

        v1 = recipe_service.get_version(session, recipe.id, 1)
        assert v1.ingredients[3].baker_pct == 5.0
        assert v1.notes == "first attempt"

    def test_versions_are_numbered_sequentially(self, session):
        recipe = make(session)
        for _ in range(3):
            recipe_service.add_version(
                session, recipe, ingredients=rye(), stages=stages()
            )
        session.commit()
        assert sorted(v.version for v in recipe.versions) == [1, 2, 3, 4]

    def test_name_and_category_are_not_versioned(self, session):
        """They label the whole recipe, so renaming is not a new version."""
        recipe = make(session)
        recipe_service.update_recipe_meta(
            session, recipe, name="Borodinsky (rye)", category=RecipeCategory.RYE
        )
        session.commit()
        assert recipe.name == "Borodinsky (rye)"
        assert len(recipe.versions) == 1

    def test_specs_from_version_round_trips(self, session):
        recipe = make(session)
        ingredients, stage_specs = recipe_service.specs_from_version(
            recipe.latest_version
        )
        assert [i.name for i in ingredients] == [s.name for s in rye()]
        assert [i.baker_pct for i in ingredients] == [s.baker_pct for s in rye()]
        assert [s.duration_min for s in stage_specs] == [
            s.duration_min for s in stages()
        ]


class TestArchiving:
    def test_archive_hides_it_from_the_list_but_keeps_it(self, session):
        recipe = make(session)
        recipe_service.set_archived(session, recipe, True)
        session.commit()

        assert recipe_service.list_recipes(session) == []
        kept = recipe_service.list_recipes(session, include_archived=True)
        assert [r.id for r in kept] == [recipe.id]
        # Still readable, because a bake may point at it.
        assert recipe_service.get_recipe(session, recipe.id) is not None

    def test_unarchive_brings_it_back(self, session):
        recipe = make(session)
        recipe_service.set_archived(session, recipe, True)
        recipe_service.set_archived(session, recipe, False)
        session.commit()
        assert [r.id for r in recipe_service.list_recipes(session)] == [recipe.id]


class TestDiff:
    def _two_versions(self, session, ingredients=None, stage_specs=None):
        recipe = make(session)
        recipe_service.add_version(
            session, recipe,
            ingredients=ingredients if ingredients is not None else rye(),
            stages=stage_specs if stage_specs is not None else stages(),
        )
        session.commit()
        return (
            recipe_service.get_version(session, recipe.id, 1),
            recipe_service.get_version(session, recipe.id, 2),
        )

    def test_no_changes_is_empty(self, session):
        before, after = self._two_versions(session)
        assert diff_versions(before, after).is_empty

    def test_a_changed_percentage_is_reported(self, session):
        changed = rye()
        changed[3].baker_pct = 8.0
        before, after = self._two_versions(session, ingredients=changed)

        diff = diff_versions(before, after)
        assert len(diff.ingredients) == 1
        line = diff.ingredients[0]
        assert line.kind == "changed"
        assert line.name == "Red rye malt"
        assert [c.field for c in line.changes] == ["baker_pct"]
        assert line.changes[0].label == "baker's %"
        assert (line.changes[0].before, line.changes[0].after) == (5.0, 8.0)
        assert "5 → 8" in line.summary

    def test_an_added_ingredient_is_reported(self, session):
        more = rye() + [
            IngredientSpec("Coriander", IngredientRole.OTHER, 1.0)
        ]
        before, after = self._two_versions(session, ingredients=more)

        diff = diff_versions(before, after)
        assert [(l.kind, l.name) for l in diff.ingredients] == [
            ("added", "Coriander")
        ]

    def test_a_removed_ingredient_is_reported(self, session):
        fewer = rye()[:-1]
        before, after = self._two_versions(session, ingredients=fewer)

        diff = diff_versions(before, after)
        assert [(l.kind, l.name) for l in diff.ingredients] == [
            ("removed", "Salt")
        ]

    def test_matching_is_by_name_not_position(self, session):
        """Reordering the list is not a change to the ingredients."""
        shuffled = [rye()[1], rye()[0]] + rye()[2:]
        before, after = self._two_versions(session, ingredients=shuffled)
        assert diff_versions(before, after).ingredients == []

    def test_a_reordered_stage_is_a_move(self, session):
        """Order matters for stages: proof before bake is a different bread."""
        reordered = stages()
        reordered[3], reordered[4] = reordered[4], reordered[3]
        before, after = self._two_versions(session, stage_specs=reordered)

        diff = diff_versions(before, after)
        kinds = {(l.kind, l.name) for l in diff.stages}
        assert ("moved", "proof") in kinds
        assert ("moved", "bake") in kinds

    def test_a_longer_scald_is_reported(self, session):
        longer = stages()
        longer[0].duration_min = 300
        before, after = self._two_versions(session, stage_specs=longer)

        diff = diff_versions(before, after)
        assert len(diff.stages) == 1
        assert diff.stages[0].name == "scald (zavarka)"
        assert "240 → 300" in diff.stages[0].summary

    def test_count_adds_both_sides_up(self, session):
        changed = rye()
        changed[3].baker_pct = 8.0
        longer = stages()
        longer[0].duration_min = 300
        before, after = self._two_versions(
            session, ingredients=changed, stage_specs=longer
        )
        assert diff_versions(before, after).count == 2

    def test_duplicate_names_are_paired_in_order(self, session):
        twice = [
            IngredientSpec("Water", IngredientRole.WATER, 50.0),
            IngredientSpec("Water", IngredientRole.WATER, 30.0),
            IngredientSpec("Rye", IngredientRole.FLOUR, 100.0),
        ]
        recipe = recipe_service.create_recipe(
            session, name="Odd", category=RecipeCategory.RYE,
            ingredients=twice, stages=[],
        )
        edited = [
            IngredientSpec("Water", IngredientRole.WATER, 50.0),
            IngredientSpec("Water", IngredientRole.WATER, 35.0),
            IngredientSpec("Rye", IngredientRole.FLOUR, 100.0),
        ]
        recipe_service.add_version(session, recipe, ingredients=edited, stages=[])
        session.commit()

        diff = diff_versions(
            recipe_service.get_version(session, recipe.id, 1),
            recipe_service.get_version(session, recipe.id, 2),
        )
        # Only the second water line moved.
        assert len(diff.ingredients) == 1
        assert (
            diff.ingredients[0].changes[0].before,
            diff.ingredients[0].changes[0].after,
        ) == (30.0, 35.0)


class TestEquipmentPrograms:
    def test_create_and_list(self, session):
        recipe_service.create_program(
            session, name="Whole Wheat", device="West Bend 41300",
            total_min=230, notes="3 rises",
        )
        session.commit()
        programs = recipe_service.list_programs(session)
        assert [p.name for p in programs] == ["Whole Wheat"]
        assert programs[0].total_min == 230

    def test_archived_programs_are_hidden_but_kept(self, session):
        program = recipe_service.create_program(session, name="Basic")
        recipe_service.update_program(session, program, archived=True)
        session.commit()

        assert recipe_service.list_programs(session) == []
        assert len(recipe_service.list_programs(session, include_archived=True)) == 1
