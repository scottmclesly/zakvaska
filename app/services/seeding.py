"""Putting reference data into an empty notebook, safely.

Three rules, because this runs against a database with real bakes in it:

* **Add only.** Nothing here updates or deletes a row that is already
  there. A program or recipe whose key matches is left exactly as it is
  and reported as skipped — including its children, so a recipe you have
  since edited never gets a second version from a seed run.
* **Idempotent.** Keyed on what a human would call the same thing: a
  program by device and name, a recipe by name and source. Running it
  twice adds nothing the second time.
* **Rehearsable.** `dry_run=True` reports exactly what a real run would
  do and writes nothing, not even to the session.

Recipes go in through `app.services.recipes`, not by building ORM objects
here, so seeded recipes get the same versioning and validation as typed
ones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import westbend
from app.models.enums import IngredientRole, RecipeCategory
from app.models.recipe import EquipmentCycle, EquipmentProgram, Recipe
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec

log = logging.getLogger("zakvaska.seeding")


@dataclass
class SeedReport:
    """What a run did, or would have done."""

    dry_run: bool = False
    programs_added: list[str] = field(default_factory=list)
    programs_skipped: list[str] = field(default_factory=list)
    cycles_added: int = 0
    recipes_added: list[str] = field(default_factory=list)
    recipes_skipped: list[str] = field(default_factory=list)

    @property
    def added_anything(self) -> bool:
        return bool(self.programs_added or self.recipes_added)

    def lines(self) -> list[str]:
        head = "Would add" if self.dry_run else "Added"
        out = [
            f"{head} {len(self.programs_added)} programs "
            f"({self.cycles_added} cycle rows), "
            f"{len(self.recipes_added)} recipes.",
            f"Left alone: {len(self.programs_skipped)} programs, "
            f"{len(self.recipes_skipped)} recipes already there.",
        ]
        for name in self.programs_added:
            out.append(f"  + program  {name}")
        for name in self.recipes_added:
            out.append(f"  + recipe   {name}")
        for name in self.programs_skipped:
            out.append(f"  = program  {name} (already there)")
        for name in self.recipes_skipped:
            out.append(f"  = recipe   {name} (already there)")
        return out


# --- Equipment -------------------------------------------------------------


def find_program(
    session: Session, device: str, name: str
) -> EquipmentProgram | None:
    """A program is the same program if the device and the name match."""
    return session.scalars(
        select(EquipmentProgram).where(
            EquipmentProgram.device == device, EquipmentProgram.name == name
        )
    ).first()


def seed_programs(
    session: Session, report: SeedReport, *, dry_run: bool = False
) -> SeedReport:
    for spec in westbend.PROGRAMS:
        existing = find_program(session, westbend.DEVICE, spec["name"])
        label = f"{westbend.DEVICE} — {spec['menu_no']}. {spec['name']}"
        if existing is not None:
            report.programs_skipped.append(label)
            continue

        report.programs_added.append(label)
        report.cycles_added += len(spec["cycles"])
        if dry_run:
            continue

        # The headline total is the 2 lb one where there are sizes, so a
        # list of programs shows the number a person would quote.
        cycles = spec["cycles"]
        headline = next(
            (c["total_min"] for c in cycles if c["loaf_lb"] == 2.0),
            cycles[0]["total_min"],
        )
        program = recipe_service.create_program(
            session,
            name=spec["name"],
            device=westbend.DEVICE,
            menu_no=spec["menu_no"],
            total_min=headline,
            notes=spec["notes"],
        )
        for cycle in cycles:
            session.add(EquipmentCycle(program_id=program.id, **cycle))
        session.flush()

    return report


# --- Recipes ---------------------------------------------------------------


def find_recipe(session: Session, name: str, source: str | None) -> Recipe | None:
    """Keyed on name and source: two Borodinskys from two books are two recipes.

    Archived recipes count. Seeding one back after it was archived on
    purpose would be a surprise, not a service.
    """
    stmt = select(Recipe).where(Recipe.name == name)
    stmt = (
        stmt.where(Recipe.source == source)
        if source is not None
        else stmt.where(Recipe.source.is_(None))
    )
    return session.scalars(stmt).first()


def _programs_by_name(session: Session) -> dict[str, EquipmentProgram]:
    return {
        program.name: program
        for program in session.scalars(
            select(EquipmentProgram).where(
                EquipmentProgram.device == westbend.DEVICE
            )
        )
    }


def seed_recipes(
    session: Session, report: SeedReport, *, dry_run: bool = False
) -> SeedReport:
    from app.data.recipes import RECIPES

    known = _programs_by_name(session)

    for spec in RECIPES:
        if find_recipe(session, spec["name"], spec.get("source")) is not None:
            report.recipes_skipped.append(spec["name"])
            continue

        report.recipes_added.append(spec["name"])
        if dry_run:
            continue

        recipe = recipe_service.create_recipe(
            session,
            name=spec["name"],
            category=RecipeCategory(spec["category"]),
            source=spec.get("source"),
            source_ref=spec.get("source_ref"),
            notes=spec["notes"],
            ingredients=[
                IngredientSpec(
                    name=item["name"],
                    role=IngredientRole(item["role"]),
                    baker_pct=item["pct"],
                    notes=item.get("notes"),
                )
                for item in spec["ingredients"]
            ],
            stages=[
                StageSpec(
                    name=stage["name"],
                    duration_min=stage.get("min"),
                    temp_c=stage.get("temp_c"),
                    notes=stage.get("notes"),
                )
                for stage in spec.get("stages", [])
            ],
        )
        program_name = spec.get("program")
        version = recipe.latest_version
        if program_name and program_name in known:
            version.default_program_id = known[program_name].id
        version.default_loaf_size = spec.get("loaf_size")
        version.default_crust = spec.get("crust")
        session.flush()

    return report


# --- Both ------------------------------------------------------------------


def seed_all(session: Session, *, dry_run: bool = False) -> SeedReport:
    report = SeedReport(dry_run=dry_run)
    seed_programs(session, report, dry_run=dry_run)
    seed_recipes(session, report, dry_run=dry_run)
    if not dry_run:
        log.info(
            "seeded %d programs and %d recipes",
            len(report.programs_added),
            len(report.recipes_added),
        )
    return report
