"""Equipment programs, typed in from the bread maker's manual."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.recipe import EquipmentProgram
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import recipes as recipe_service
from app.templates_env import render

router = APIRouter(prefix="/equipment")

Ctx = Annotated[ViewContext, Depends(get_view_context)]


def _see_other(url: str = "/equipment") -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _load(ctx: ViewContext, program_id: int) -> EquipmentProgram:
    program = ctx.session.get(EquipmentProgram, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="No such program")
    return program


@router.get("", response_class=HTMLResponse)
def list_programs(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request,
        ctx=ctx,
        name="equipment/list.html",
        context={
            "title": "Equipment programs",
            "programs": recipe_service.list_programs(ctx.session),
            "archived": [
                p
                for p in recipe_service.list_programs(ctx.session, include_archived=True)
                if p.archived
            ],
            "errors": [],
        },
    )


@router.post("/new")
def create_program(
    request: Request,
    ctx: Ctx,
    name: Annotated[str, Form()] = "",
    device: Annotated[str, Form()] = "",
    total_min: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    errors: list[str] = []
    if not f.opt_str(name):
        errors.append("A program needs a name.")
    try:
        minutes = f.opt_int(total_min, field="Total minutes")
    except ValueError as exc:
        errors.append(str(exc))
        minutes = None

    if errors:
        return render(
            request=request,
            ctx=ctx,
            name="equipment/list.html",
            context={
                "title": "Equipment programs",
                "programs": recipe_service.list_programs(ctx.session),
                "archived": [],
                "errors": errors,
            },
            status_code=400,
        )

    recipe_service.create_program(
        ctx.session,
        name=f.opt_str(name),
        device=f.opt_str(device),
        total_min=minutes,
        notes=f.opt_str(notes),
    )
    ctx.session.commit()
    return _see_other()


@router.post("/{program_id}/edit")
def edit_program(
    ctx: Ctx,
    program_id: int,
    name: Annotated[str, Form()] = "",
    device: Annotated[str, Form()] = "",
    total_min: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    program = _load(ctx, program_id)
    if not f.opt_str(name):
        raise HTTPException(status_code=400, detail="A program needs a name")

    recipe_service.update_program(
        ctx.session,
        program,
        name=f.opt_str(name),
        device=f.opt_str(device),
        total_min=f.opt_int(total_min, field="Total minutes"),
        notes=f.opt_str(notes),
    )
    ctx.session.commit()
    return _see_other()


@router.post("/{program_id}/archive")
def archive_program(
    ctx: Ctx, program_id: int, archived: Annotated[str, Form()] = "1"
):
    program = _load(ctx, program_id)
    recipe_service.update_program(ctx.session, program, archived=archived == "1")
    ctx.session.commit()
    return _see_other()
