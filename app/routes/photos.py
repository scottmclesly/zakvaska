"""Uploading, serving and comparing photos."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.models.enums import PhotoOwner
from app.routes import forms as f
from app.routes.deps import ViewContext, get_view_context
from app.services import photos as photo_service
from app.templates_env import render

router = APIRouter(prefix="/photos")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

# Photos never change once written, so they can be cached hard. The URL
# changes when the photo does, because a new photo is a new row.
CACHE_FOREVER = {"Cache-Control": "private, max-age=31536000, immutable"}


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _load(ctx: ViewContext, photo_id: int):
    photo = photo_service.get_photo(ctx.session, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="No such photo")
    return photo


def _home(ctx: ViewContext, photo) -> str:
    return photo_service.owner_url(ctx.session, photo.owner_type, photo.owner_id) or "/"


@router.post("/upload")
async def upload(
    ctx: Ctx,
    owner_type: Annotated[str, Form()],
    owner_id: Annotated[int, Form()],
    caption: Annotated[str, Form()] = "",
    photo: Annotated[UploadFile | None, File()] = None,
):
    try:
        owner = PhotoOwner(owner_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown photo owner") from None

    back = photo_service.owner_url(ctx.session, owner, owner_id)
    if back is None:
        raise HTTPException(status_code=404, detail="Nothing to attach that to")

    if photo is None or not photo.filename:
        # An empty file field is not an error: the form is shared with pages
        # where a photo is optional.
        return _see_other(back)

    data = await photo.read()
    try:
        photo_service.attach(
            ctx.session,
            owner_type=owner,
            owner_id=owner_id,
            data=data,
            caption=f.opt_str(caption),
            now=ctx.now,
        )
    except photo_service.PhotoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    ctx.session.commit()
    return _see_other(back)


@router.get("/{photo_id}/file")
def serve(ctx: Ctx, photo_id: int) -> FileResponse:
    photo = _load(ctx, photo_id)
    path = photo_service.absolute(photo.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That photo's file is missing")
    return FileResponse(path, media_type="image/jpeg", headers=CACHE_FOREVER)


@router.get("/{photo_id}/thumb")
def serve_thumb(ctx: Ctx, photo_id: int) -> FileResponse:
    photo = _load(ctx, photo_id)
    path = photo_service.absolute(photo.thumb_path)
    if not path.is_file():
        # Fall back to the full image rather than showing a broken thumbnail.
        path = photo_service.absolute(photo.path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="That photo's file is missing")
    return FileResponse(path, media_type="image/jpeg", headers=CACHE_FOREVER)


@router.get("/{photo_id}/original")
def serve_original(ctx: Ctx, photo_id: int) -> FileResponse:
    """The file exactly as it was uploaded — HEIC included.

    A download rather than something a page embeds: most browsers cannot
    render HEIC, and this is the copy that still carries the camera's EXIF.
    """
    photo = _load(ctx, photo_id)
    if not photo.original_path:
        raise HTTPException(
            status_code=404, detail="That photo was stored before originals were kept"
        )
    path = photo_service.absolute(photo.original_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="That photo's file is missing")
    return FileResponse(
        path,
        media_type=photo_service.media_type_for(photo.original_path),
        filename=f"zakvaska-photo-{photo.id}{path.suffix}",
        headers=CACHE_FOREVER,
    )


@router.post("/{photo_id}/caption")
def caption(ctx: Ctx, photo_id: int, caption: Annotated[str, Form()] = ""):
    photo = _load(ctx, photo_id)
    photo_service.set_caption(ctx.session, photo, f.opt_str(caption))
    ctx.session.commit()
    return _see_other(_home(ctx, photo))


@router.post("/{photo_id}/delete")
def delete(ctx: Ctx, photo_id: int):
    photo = _load(ctx, photo_id)
    back = _home(ctx, photo)
    photo_service.delete_photo(ctx.session, photo)
    ctx.session.commit()
    return _see_other(back)


@router.get("/compare", response_class=HTMLResponse)
def compare(
    request: Request, ctx: Ctx, a: int | None = None, b: int | None = None
) -> HTMLResponse:
    """Two crumb shots side by side — the only way to see a change in crumb."""
    available = photo_service.bake_photos(ctx.session)
    by_id = {photo.id: photo for photo in available}
    return render(
        request=request,
        ctx=ctx,
        name="photos/compare.html",
        context={
            "title": "Compare crumb",
            "available": available,
            "left": by_id.get(a),
            "right": by_id.get(b),
            "owners": photo_service.bake_photo_owners(ctx.session, available),
        },
    )
