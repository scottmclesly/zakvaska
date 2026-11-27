"""Recipe pages: list, create, version detail, edit-as-new-version, diff."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.models.enums import (
    INGREDIENT_SUGGESTIONS,
    STAGE_SUGGESTIONS,
    IngredientRole,
    RecipeCategory,
)
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import bakes as bake_service
from app.services import browse
from app.services import measures
from app.services import recipes as recipe_service
from app.services import scaling
from app.services.recipe_diff import diff_versions
from app.services.units import temp_to_celsius
from app.templates_env import render

router = APIRouter(prefix="/recipes")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

# A blank row the form starts with, so there is always something to type into.
BLANK_INGREDIENT = recipe_service.IngredientSpec(
    name="", role=IngredientRole.FLOUR, baker_pct=0.0
)
BLANK_STAGE = recipe_service.StageSpec(name="")


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _load(ctx: ViewContext, recipe_id: int):
    recipe = recipe_service.get_recipe(ctx.session, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="No such recipe")
    return recipe


def _load_version(ctx: ViewContext, recipe_id: int, version: int):
    found = recipe_service.get_version(ctx.session, recipe_id, version)
    if found is None:
        raise HTTPException(status_code=404, detail="No such recipe version")
    return found


def _parse_rows(
    ctx: ViewContext,
    names: list[str],
    roles: list[str],
    percents: list[str],
    amounts: list[str],
    ing_notes: list[str],
    stage_names: list[str],
    durations: list[str],
    temps: list[str],
    stage_notes: list[str],
) -> tuple[list, list, float | None, list[str]]:
    """Turn the parallel form arrays into specs. Blank rows are dropped.

    A row can be given as an amount ("3 cups", "12 oz") or as a baker's
    percentage. Amounts win: when any are filled in, the percentages are
    worked out from them and the flour weight they came from is kept on the
    version, so the recipe reads back in the unit it was written in.
    """
    errors: list[str] = []
    ingredients: list[recipe_service.IngredientSpec] = []

    for index, raw_name in enumerate(names):
        name = f.opt_str(raw_name)
        if name is None:
            continue  # an empty row is just an unused row

        role_value = roles[index] if index < len(roles) else IngredientRole.OTHER.value
        role = IngredientRole(role_value)

        try:
            grams = f.opt_weight(
                amounts[index] if index < len(amounts) else "",
                ctx.weight_unit,
                field=f"Amount for {name}",
                name=name,
                role=role,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        raw_pct = percents[index] if index < len(percents) else ""
        if grams is None:
            try:
                pct = f.req_float(raw_pct, field=f"Percentage for {name}")
            except ValueError as exc:
                errors.append(str(exc))
                continue
        else:
            # Worked out once every row is in, by percentages_from_amounts.
            pct = f.opt_float(raw_pct, field=f"Percentage for {name}") or 0.0

        if pct < 0:
            errors.append(f"{name} cannot be a negative percentage.")
            continue

        ingredients.append(
            recipe_service.IngredientSpec(
                name=name,
                role=role,
                baker_pct=pct,
                notes=f.opt_str(ing_notes[index] if index < len(ing_notes) else ""),
                grams=grams,
            )
        )

    batch_flour_g: float | None = None
    if any(spec.grams is not None for spec in ingredients):
        batch_flour_g = recipe_service.percentages_from_amounts(ingredients)
        if batch_flour_g is None:
            errors.append(
                "Amounts need a flour to be a percentage of: give an amount "
                "on at least one ingredient whose role is flour."
            )

    stages: list[recipe_service.StageSpec] = []
    for index, raw_name in enumerate(stage_names):
        name = f.opt_str(raw_name)
        if name is None:
            continue
        try:
            duration = f.opt_int(
                durations[index] if index < len(durations) else "",
                field=f"Duration for {name}",
            )
            typed_temp = f.opt_float(
                temps[index] if index < len(temps) else "",
                field=f"Temperature for {name}",
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue

        stages.append(
            recipe_service.StageSpec(
                name=name,
                duration_min=duration,
                # Typed in the user's unit; stored in Celsius.
                temp_c=temp_to_celsius(typed_temp, ctx.temp_unit),
                notes=f.opt_str(stage_notes[index] if index < len(stage_notes) else ""),
            )
        )

    return ingredients, stages, batch_flour_g, errors


def _amount_inputs(ctx: ViewContext, specs) -> list[str]:
    """Each row's amount, written in the unit the switch is showing.

    A recipe typed in cups comes back in cups; one given as percentages has
    no amount to show and gets an empty field.
    """
    return [
        measures.input_text(
            getattr(spec, "grams", None),
            ctx.weight_unit,
            name=spec.name,
            role=spec.role,
        )
        for spec in specs
    ]


def _form_context(ctx: ViewContext, *, recipe=None, ingredients=None, stages=None,
                  errors=None, name="", category=RecipeCategory.OTHER.value,
                  notes="", amounts=None) -> dict:
    rows = ingredients or [BLANK_INGREDIENT]
    return {
        "title": "Edit recipe" if recipe else "New recipe",
        "recipe": recipe,
        "categories": list(RecipeCategory),
        "roles": list(IngredientRole),
        "ingredients": rows,
        # Echoed back as typed after a failed submission; otherwise worked
        # out from the stored amounts.
        "amounts": amounts if amounts is not None else _amount_inputs(ctx, rows),
        "amount_placeholder": measures.input_placeholder(ctx.weight_unit),
        "stages": stages or [BLANK_STAGE],
        "ingredient_suggestions": INGREDIENT_SUGGESTIONS,
        "stage_suggestions": STAGE_SUGGESTIONS,
        "errors": errors or [],
        "name": name,
        "category": category,
        "notes": notes,
    }


@router.get("", response_class=HTMLResponse)
def list_recipes(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request,
        ctx=ctx,
        name="recipes/list.html",
        context={
            "title": "Recipes",
            "recipes": (recipes := recipe_service.list_recipes(ctx.session)),
            # What each card shows beyond the name: see services/browse.py.
            "cards": (cards := browse.recipe_cards(ctx.session, recipes)),
            # The same cards, shelved for browsing: yours first, then by family.
            "shelves": browse.recipe_shelves(cards),
            "archived": [
                r
                for r in recipe_service.list_recipes(ctx.session, include_archived=True)
                if r.archived
            ],
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_recipe_form(request: Request, ctx: Ctx) -> HTMLResponse:
    return render(
        request=request, ctx=ctx, name="recipes/form.html",
        context=_form_context(ctx),
    )


@router.post("/new")
def create_recipe(
    request: Request,
    ctx: Ctx,
    name: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = RecipeCategory.OTHER.value,
    notes: Annotated[str, Form()] = "",
    ingredient_name: Annotated[list[str], Form()] = [],
    ingredient_role: Annotated[list[str], Form()] = [],
    ingredient_pct: Annotated[list[str], Form()] = [],
    ingredient_amount: Annotated[list[str], Form()] = [],
    ingredient_notes: Annotated[list[str], Form()] = [],
    stage_name: Annotated[list[str], Form()] = [],
    stage_duration: Annotated[list[str], Form()] = [],
    stage_temp: Annotated[list[str], Form()] = [],
    stage_notes: Annotated[list[str], Form()] = [],
):
    ingredients, stages, batch_flour_g, errors = _parse_rows(
        ctx, ingredient_name, ingredient_role, ingredient_pct,
        ingredient_amount, ingredient_notes,
        stage_name, stage_duration, stage_temp, stage_notes,
    )
    if not f.opt_str(name):
        errors.append("A recipe needs a name.")

    if errors:
        return render(
            request=request, ctx=ctx, name="recipes/form.html",
            context=_form_context(
                ctx, ingredients=ingredients or None, stages=stages or None,
                errors=errors, name=name, category=category, notes=notes,
                amounts=ingredient_amount or None,
            ),
            status_code=400,
        )

    recipe = recipe_service.create_recipe(
        ctx.session,
        name=f.opt_str(name),
        category=RecipeCategory(category),
        ingredients=ingredients,
        stages=stages,
        notes=f.opt_str(notes),
        batch_flour_g=batch_flour_g,
    )
    ctx.session.commit()
    return _see_other(f"/recipes/{recipe.id}")


@router.get("/{recipe_id}")
def latest_version(ctx: Ctx, recipe_id: int):
    recipe = _load(ctx, recipe_id)
    latest = recipe.latest_version
    if latest is None:
        raise HTTPException(status_code=404, detail="Recipe has no versions")
    return _see_other(f"/recipes/{recipe.id}/v/{latest.version}")


@router.get("/{recipe_id}/v/{version}", response_class=HTMLResponse)
def version_detail(
    request: Request,
    ctx: Ctx,
    recipe_id: int,
    version: int,
    flour: str | None = None,
    dough: str | None = None,
) -> HTMLResponse:
    found = _load_version(ctx, recipe_id, version)

    # Scale-to view. Flour wins if somehow both are given. The fields are
    # read in whatever unit the switch is showing — "1 lb 2 oz" as readily
    # as 500 — so a recipe can be scaled in the unit it is written in.
    scaled = None
    scale_error = None
    asked_flour = f.opt_str(flour)
    asked_dough = f.opt_str(dough)
    # A recipe written as real amounts shows them without being asked: that
    # batch is what the recipe *is*, and retyping it to read it would be
    # silly. One given as percentages has no size of its own and waits.
    from_batch = not asked_flour and not asked_dough and bool(found.batch_flour_g)

    try:
        if asked_flour:
            scaled = scaling.scale_to_flour(
                found.ingredients,
                f.opt_total_weight(
                    flour, ctx.weight_unit, field="Total flour", flour=True
                ),
            )
        elif asked_dough:
            scaled = scaling.scale_to_dough_weight(
                found.ingredients,
                f.opt_total_weight(dough, ctx.weight_unit, field="Dough weight"),
            )
        elif from_batch:
            scaled = scaling.scale_to_flour(
                found.ingredients, found.batch_flour_g
            )
    except ValueError as exc:
        scale_error = str(exc)

    return render(
        request=request,
        ctx=ctx,
        name="recipes/version.html",
        context={
            "title": f"{found.recipe.name} {found.label}",
            "recipe": found.recipe,
            "version": found,
            "is_latest": found.recipe.latest_version.id == found.id,
            "flour_pct": scaling.flour_percentage(found.ingredients),
            "total_pct": scaling.total_percentage(found.ingredients),
            "scaled": scaled,
            "scale_error": scale_error,
            "scaled_from_batch": from_batch and scaled is not None,
            # The scale field shows what was typed, or the batch the recipe
            # was written at, in the unit on display.
            "flour_input": asked_flour
            or (
                measures.input_total_text(
                    found.batch_flour_g, ctx.weight_unit, flour=True
                )
                if from_batch
                else ""
            ),
            "dough_input": asked_dough or "",
            "total_placeholder": measures.input_total_placeholder(ctx.weight_unit),
            "flour_placeholder": measures.input_total_placeholder(
                ctx.weight_unit, flour=True
            ),
            # Bakes from this exact version, newest first.
            "bakes": [b for b in found.bakes if not b.archived],
        },
    )


@router.get("/{recipe_id}/edit", response_class=HTMLResponse)
def edit_recipe_form(request: Request, ctx: Ctx, recipe_id: int) -> HTMLResponse:
    recipe = _load(ctx, recipe_id)
    latest = recipe.latest_version
    ingredients, stages = (
        recipe_service.specs_from_version(latest) if latest else ([], [])
    )
    return render(
        request=request, ctx=ctx, name="recipes/form.html",
        context=_form_context(
            ctx, recipe=recipe,
            ingredients=ingredients or None, stages=stages or None,
            name=recipe.name, category=recipe.category.value,
        ),
    )


@router.post("/{recipe_id}/edit")
def edit_recipe(
    request: Request,
    ctx: Ctx,
    recipe_id: int,
    name: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = RecipeCategory.OTHER.value,
    notes: Annotated[str, Form()] = "",
    ingredient_name: Annotated[list[str], Form()] = [],
    ingredient_role: Annotated[list[str], Form()] = [],
    ingredient_pct: Annotated[list[str], Form()] = [],
    ingredient_amount: Annotated[list[str], Form()] = [],
    ingredient_notes: Annotated[list[str], Form()] = [],
    stage_name: Annotated[list[str], Form()] = [],
    stage_duration: Annotated[list[str], Form()] = [],
    stage_temp: Annotated[list[str], Form()] = [],
    stage_notes: Annotated[list[str], Form()] = [],
):
    recipe = _load(ctx, recipe_id)
    ingredients, stages, batch_flour_g, errors = _parse_rows(
        ctx, ingredient_name, ingredient_role, ingredient_pct,
        ingredient_amount, ingredient_notes,
        stage_name, stage_duration, stage_temp, stage_notes,
    )
    if not f.opt_str(name):
        errors.append("A recipe needs a name.")

    if errors:
        return render(
            request=request, ctx=ctx, name="recipes/form.html",
            context=_form_context(
                ctx, recipe=recipe, ingredients=ingredients or None,
                stages=stages or None, errors=errors, name=name,
                category=category, notes=notes,
                amounts=ingredient_amount or None,
            ),
            status_code=400,
        )

    recipe_service.update_recipe_meta(
        ctx.session, recipe, name=f.opt_str(name), category=RecipeCategory(category)
    )
    # The edit itself becomes a new version; the old one stays readable.
    version = recipe_service.add_version(
        ctx.session, recipe,
        ingredients=ingredients, stages=stages, notes=f.opt_str(notes),
        batch_flour_g=batch_flour_g,
    )
    ctx.session.commit()
    return _see_other(f"/recipes/{recipe.id}/v/{version.version}")


@router.post("/{recipe_id}/archive")
def archive_recipe(ctx: Ctx, recipe_id: int, archived: Annotated[str, Form()] = "1"):
    recipe = _load(ctx, recipe_id)
    recipe_service.set_archived(ctx.session, recipe, archived == "1")
    ctx.session.commit()
    return _see_other(f"/recipes/{recipe.id}")


@router.get("/{recipe_id}/diff", response_class=HTMLResponse)
def diff(
    request: Request,
    ctx: Ctx,
    recipe_id: int,
    from_version: int | None = None,
    to_version: int | None = None,
) -> HTMLResponse:
    recipe = _load(ctx, recipe_id)
    numbers = sorted(v.version for v in recipe.versions)
    if len(numbers) < 2:
        raise HTTPException(
            status_code=404, detail="This recipe has only one version so far"
        )

    earlier = from_version or numbers[-2]
    later = to_version or numbers[-1]
    before = _load_version(ctx, recipe_id, earlier)
    after = _load_version(ctx, recipe_id, later)

    return render(
        request=request,
        ctx=ctx,
        name="recipes/diff.html",
        context={
            "title": f"{recipe.name}: v{earlier} → v{later}",
            "recipe": recipe,
            "diff": diff_versions(before, after),
            "before": before,
            "after": after,
            "versions": numbers,
        },
    )
