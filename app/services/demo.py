"""A demo notebook, for someone opening zakvaska for the first time.

An empty notebook shows an empty shelf, and an empty shelf does not say what
the thing is for. `load` fills it with a few days of plausible history: two
rye jars side by side (a homemade one and a purchased control, which is the
experiment this notebook was built around), the recipe library, and one
finished loaf with its result written up.

Three rules:

* **Only into an empty notebook.** `can_load` is false the moment there is
  a jar, archived or not, so this can never be mixed into real records.
* **Through the services.** Jars, feedings and the bake are written by the
  same functions the forms call, so the demo cannot hold anything a person
  could not have typed.
* **Labelled.** Everything it adds says "(demo)" in its name, and goes away
  the usual way: archive it.

`load_library` is the recipe library on its own, for a notebook that wants
the reference recipes and the bread maker's programs without the pretend
jars. It is `scripts/seed.sh` as a button.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import BakeMethod, BakeStatus, BubbleLevel, JarOrigin, JarState
from app.models.jar import Jar
from app.models.recipe import Recipe
from app.services import bakes as bake_service
from app.services import jars as jar_service
from app.services import seeding

#: The seeded recipe the demo loaf is baked from.
DEMO_RECIPE = ("Borodinsky (demo)", "zakvaska")

#: Twelve hours apart, the last one nine hours ago: the jars are due in
#: three hours, so a newcomer sees a countdown and then sees an alert fire.
FEED_EVERY_H = 12
LAST_FEED_AGO_H = 9
FEEDINGS = 8

JARS = (
    {
        "name": "Rye (demo)",
        "origin": JarOrigin.HOMEMADE,
        "culture_name": "Homemade whole rye",
        "is_control": False,
        "notes": "Demo jar. Started from whole rye flour and water.",
        # Rise, in mm above a 30 mm start, four and eight hours after a feed.
        "rise": (22.0, 38.0),
    },
    {
        "name": "Soviet rye (demo)",
        "origin": JarOrigin.PURCHASED,
        "culture_name": "Purchased rye culture",
        "is_control": True,
        "notes": "Demo jar. The control: a bought culture, fed exactly like"
                 " the homemade one so the two can be compared.",
        "rise": (17.0, 31.0),
    },
)


def can_load(session: Session) -> bool:
    """True only for a notebook that has never had a jar."""
    return session.scalar(select(func.count()).select_from(Jar)) == 0


def library_missing(session: Session) -> bool:
    """True when there is not one recipe, so the library can be offered."""
    return session.scalar(select(func.count()).select_from(Recipe)) == 0


def load_library(session: Session) -> seeding.SeedReport:
    return seeding.seed_all(session)


def _jar(session: Session, spec: dict, now: datetime) -> Jar:
    first_feed = now - timedelta(
        hours=LAST_FEED_AGO_H + FEED_EVERY_H * (FEEDINGS - 1)
    )
    jar = jar_service.create_jar(
        session,
        name=spec["name"],
        origin=spec["origin"],
        culture_name=spec["culture_name"],
        flour_type="whole rye",
        state=JarState.ACTIVE,
        is_control=spec["is_control"],
        notes=spec["notes"],
        created_at=first_feed - timedelta(hours=1),
    )
    for n in range(FEEDINGS):
        fed_at = first_feed + timedelta(hours=FEED_EVERY_H * n)
        jar_service.log_feeding(
            session,
            jar,
            fed_at=fed_at,
            starter_g=20.0,
            flour_g=40.0,
            water_g=40.0,
            flour_type="whole rye",
            water_temp_c=30.0,
            ambient_temp_c=24.0,
        )
        at_four, at_eight = spec["rise"]
        for hours, rise, bubbles in (
            (4, at_four, BubbleLevel.SOME),
            (8, at_eight, BubbleLevel.MANY),
        ):
            observed_at = fed_at + timedelta(hours=hours)
            if observed_at > now:
                continue
            jar_service.log_observation(
                session,
                jar,
                observed_at=observed_at,
                start_height_mm=30.0,
                # A little livelier with each feed, as a young starter is.
                height_mm=30.0 + rise + n,
                bubbles=bubbles,
                smell="sour, fruity" if hours == 8 else "mild",
            )
    return jar


def _bake(session: Session, jar: Jar, now: datetime) -> None:
    recipe = seeding.find_recipe(session, *DEMO_RECIPE)
    if recipe is None or not recipe.versions:
        return
    version = max(recipe.versions, key=lambda v: v.version)
    # Out of the oven yesterday evening, by the look of it.
    total_min = sum(stage.duration_min or 0 for stage in version.stages)
    started = now - timedelta(hours=26, minutes=total_min)
    bake = bake_service.start_bake(
        session,
        version,
        method=BakeMethod.DUTCH_OVEN,
        jar_id=jar.id,
        total_flour_g=500.0,
        started_at=started,
        status=BakeStatus.IN_PROGRESS,
    )
    clock = started
    for log in sorted(bake.stage_logs, key=lambda entry: entry.seq):
        bake_service.start_stage(session, bake, log, clock)
        clock += timedelta(minutes=log.planned_min or 0)
        bake_service.end_stage(session, bake, log, clock)
    bake_service.save_result(
        session,
        bake,
        rating=3,
        crust="Dark and firm, a little thick on the base.",
        crumb="Dense but even. Slightly gummy at the centre.",
        taste="Coriander comes through; could take more malt.",
        rise="Modest. Domed, no cracks.",
        next_time="Demo result. Proof twenty minutes longer and let it"
                  " rest a full day before cutting.",
        now=clock,
    )


def load(session: Session, now: datetime) -> bool:
    """Fill an empty notebook. Returns False, changing nothing, if it is not."""
    if not can_load(session):
        return False
    seeding.seed_all(session)
    jars = [_jar(session, spec, now) for spec in JARS]
    _bake(session, jars[0], now)
    session.flush()
    return True
