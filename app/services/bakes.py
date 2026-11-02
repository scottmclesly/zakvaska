"""Starting a bake, running it, and recording how it came out.

The shape of the thing: a bake is created from a recipe version, which copies
that version's stages into the bake as its plan. From then on the bake is
driven by tapping stages started and finished — one write each, because this
happens with flour on your hands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.bake import Bake, BakeResult, BakeStageLog
from app.models.base import utcnow
from app.models.enums import BakeMethod, BakeStatus
from app.models.jar import Jar
from app.models.recipe import Recipe, RecipeVersion
from app.services import scaling


def _loaded(stmt):
    return stmt.options(
        selectinload(Bake.version).selectinload(RecipeVersion.recipe),
        selectinload(Bake.version).selectinload(RecipeVersion.ingredients),
        selectinload(Bake.jar),
        selectinload(Bake.program),
        selectinload(Bake.stage_logs),
        selectinload(Bake.result),
    )


# --- Reading ---------------------------------------------------------------


def get_bake(session: Session, bake_id: int) -> Bake | None:
    return session.scalars(_loaded(select(Bake).where(Bake.id == bake_id))).first()


def list_bakes(
    session: Session,
    *,
    recipe_id: int | None = None,
    jar_id: int | None = None,
    min_rating: int | None = None,
    status: BakeStatus | None = None,
    include_archived: bool = False,
) -> list[Bake]:
    """Newest first. Every filter is optional and they stack."""
    stmt = _loaded(select(Bake))

    if recipe_id is not None:
        stmt = stmt.join(Bake.version).where(RecipeVersion.recipe_id == recipe_id)
    if jar_id is not None:
        stmt = stmt.where(Bake.jar_id == jar_id)
    if status is not None:
        stmt = stmt.where(Bake.status == status)
    if min_rating is not None:
        # An inner join, so unrated bakes drop out — which is what asking for
        # "4 stars and up" means.
        stmt = stmt.join(Bake.result).where(BakeResult.rating >= min_rating)
    if not include_archived:
        stmt = stmt.where(Bake.archived.is_(False))

    return list(session.scalars(stmt.order_by(Bake.created_at.desc())))


def filter_options(session: Session) -> dict[str, list]:
    """What the bake list's filter selects can offer."""
    return {
        "recipes": list(
            session.scalars(select(Recipe).order_by(Recipe.archived, Recipe.name))
        ),
        "jars": list(session.scalars(select(Jar).order_by(Jar.archived, Jar.name))),
        "statuses": list(BakeStatus),
    }


def scaled(bake: Bake) -> scaling.ScaledRecipe | None:
    """The grams to weigh out for this loaf, or None if no flour total is set."""
    if bake.total_flour_g is None:
        return None
    return scaling.scale_to_flour(bake.version.ingredients, bake.total_flour_g)


@dataclass(frozen=True)
class Progress:
    done: int
    total: int
    running: BakeStageLog | None
    next_up: BakeStageLog | None

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.done == self.total


def progress(bake: Bake) -> Progress:
    """Where the bake has got to, for the big buttons on the running sheet."""
    logs = list(bake.stage_logs)
    running = next((log for log in logs if log.is_running), None)
    next_up = next(
        (log for log in logs if log.actual_start is None and not log.is_done), None
    )
    return Progress(
        done=sum(1 for log in logs if log.is_done),
        total=len(logs),
        running=running,
        next_up=next_up,
    )


def planned_total_min(bake: Bake) -> int | None:
    minutes = [log.planned_min for log in bake.stage_logs if log.planned_min]
    return sum(minutes) if minutes else None


def elapsed_min(bake: Bake, now: datetime) -> int | None:
    if bake.started_at is None:
        return None
    end = bake.finished_at or now
    return round((end - bake.started_at).total_seconds() / 60)


# --- Writing ---------------------------------------------------------------


def start_bake(
    session: Session,
    version: RecipeVersion,
    *,
    method: BakeMethod = BakeMethod.OVEN,
    jar_id: int | None = None,
    equipment_program_id: int | None = None,
    crust_setting: str | None = None,
    loaf_size: str | None = None,
    oven_temp_c: float | None = None,
    bake_min: int | None = None,
    total_flour_g: float | None = None,
    started_at: datetime | None = None,
    status: BakeStatus = BakeStatus.PLANNED,
) -> Bake:
    """Create a bake and copy the version's stages in as its plan."""
    bake = Bake(
        recipe_version_id=version.id,
        jar_id=jar_id,
        method=method,
        equipment_program_id=equipment_program_id,
        crust_setting=crust_setting,
        loaf_size=loaf_size,
        oven_temp_c=oven_temp_c,
        bake_min=bake_min,
        total_flour_g=total_flour_g,
        started_at=started_at,
        status=status,
    )
    session.add(bake)
    session.flush()

    # Copied, not referenced: editing the recipe later must not rewrite what
    # this loaf was baked to.
    for stage in version.stages:
        session.add(
            BakeStageLog(
                bake_id=bake.id,
                seq=stage.seq,
                name=stage.name,
                planned_min=stage.duration_min,
                planned_temp_c=stage.temp_c,
            )
        )
    session.flush()
    session.refresh(bake)
    return bake


def update_bake(session: Session, bake: Bake, **fields: Any) -> Bake:
    for key, value in fields.items():
        setattr(bake, key, value)
    session.flush()
    return bake


def get_stage(session: Session, bake: Bake, log_id: int) -> BakeStageLog | None:
    return next((log for log in bake.stage_logs if log.id == log_id), None)


def start_stage(
    session: Session, bake: Bake, log: BakeStageLog, when: datetime
) -> BakeStageLog:
    """Tapping a stage started also starts the bake, if it had not begun."""
    log.actual_start = when
    log.actual_end = None
    if bake.started_at is None:
        bake.started_at = when
    if bake.status is BakeStatus.PLANNED:
        bake.status = BakeStatus.IN_PROGRESS
    session.flush()
    return log


def end_stage(
    session: Session, bake: Bake, log: BakeStageLog, when: datetime
) -> BakeStageLog:
    # Ending a stage nobody started is still useful: it records that the
    # stage happened, even if the start went untapped.
    if log.actual_start is None:
        log.actual_start = when
    log.actual_end = when
    if bake.status is BakeStatus.PLANNED:
        bake.status = BakeStatus.IN_PROGRESS
    session.flush()
    return log


def clear_stage(session: Session, log: BakeStageLog) -> BakeStageLog:
    """Undo a mistaken tap."""
    log.actual_start = None
    log.actual_end = None
    session.flush()
    return log


def annotate_stage(
    session: Session, log: BakeStageLog, notes: str | None
) -> BakeStageLog:
    log.notes = notes
    session.flush()
    return log


def finish_bake(
    session: Session,
    bake: Bake,
    when: datetime,
    *,
    status: BakeStatus = BakeStatus.DONE,
) -> Bake:
    bake.finished_at = when
    bake.status = status
    if bake.started_at is None:
        bake.started_at = when
    session.flush()
    return bake


def reopen_bake(session: Session, bake: Bake) -> Bake:
    bake.finished_at = None
    bake.status = BakeStatus.IN_PROGRESS
    session.flush()
    return bake


def save_result(
    session: Session,
    bake: Bake,
    *,
    rating: int | None = None,
    crust: str | None = None,
    crumb: str | None = None,
    taste: str | None = None,
    rise: str | None = None,
    next_time: str | None = None,
    now: datetime | None = None,
) -> BakeResult:
    """Create or replace the bake's result. One result per bake."""
    result = bake.result
    if result is None:
        result = BakeResult(bake_id=bake.id)
        session.add(result)

    result.rating = rating
    result.crust = crust
    result.crumb = crumb
    result.taste = taste
    result.rise = rise
    result.next_time = next_time

    # Writing up a result means the loaf is out of the oven.
    if not bake.status.is_finished:
        finish_bake(session, bake, now or utcnow())

    session.flush()
    session.refresh(bake)
    return result


def set_archived(session: Session, bake: Bake, archived: bool) -> Bake:
    bake.archived = archived
    session.flush()
    return bake
