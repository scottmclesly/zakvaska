"""Export everything, and put it back."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from app.routes.deps import ViewContext, get_view_context
from app.services import backup as backup_service
from app.templates_env import render

router = APIRouter(prefix="/backup")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

log = logging.getLogger("zakvaska.backup")

# Big enough for a notebook with years of photos in it, small enough that a
# wrong file does not fill the disk before it is rejected.
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def _page(
    request: Request,
    ctx: ViewContext,
    *,
    errors: list[str] | None = None,
    done: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    counts = backup_service.current_counts(ctx.session)
    return render(
        request=request,
        ctx=ctx,
        name="backup/index.html",
        context={
            "title": "Backup",
            "counts": {name: n for name, n in counts.items() if n},
            "rows": sum(counts.values()),
            "photos": len(backup_service.photo_files()),
            "photo_bytes": backup_service.photo_bytes(),
            "suggested_name": backup_service.export_filename(ctx.now),
            "safety_copies": backup_service.safety_copies(),
            "safety_dir": backup_service.SAFETY_DIR,
            "errors": errors or [],
            "done": done,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request, ctx: Ctx, done: str | None = None) -> HTMLResponse:
    return _page(request, ctx, done=done)


@router.get("/export")
def export(ctx: Ctx) -> FileResponse:
    path, manifest = backup_service.export_to_temp(ctx.session, now=ctx.now)
    log.info(
        "exported %d rows and %d photos", manifest.rows, manifest.photos
    )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=backup_service.export_filename(ctx.now),
        # The file only exists to be sent; it goes once the send is done.
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


async def _save_upload(archive: UploadFile, path: Path) -> None:
    with path.open("wb") as handle:
        size = 0
        while chunk := await archive.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise HTTPException(status_code=413, detail="That archive is too large.")
            handle.write(chunk)


@router.post("/inspect")
async def inspect(
    request: Request,
    ctx: Ctx,
    archive: Annotated[UploadFile | None, File()] = None,
):
    """Step one of a restore: read the file and show what is in it.

    Nothing in the notebook changes here. The upload is kept, under a token,
    for the page this renders to say yes or no to.
    """
    if archive is None or not archive.filename:
        return _page(request, ctx, errors=["Choose an export to restore."], status_code=400)

    token, path = backup_service.new_pending(ctx.now)
    try:
        await _save_upload(archive, path)
        checked = backup_service.inspect(ctx.session, path)
    except backup_service.BackupError as exc:
        path.unlink(missing_ok=True)
        return _page(request, ctx, errors=[str(exc)], status_code=400)
    except BaseException:
        path.unlink(missing_ok=True)
        raise

    here = backup_service.current_counts(ctx.session)
    names = [n for n in checked.tables if checked.tables[n] or here.get(n)]
    return render(
        request=request,
        ctx=ctx,
        name="backup/confirm.html",
        context={
            "title": "Restore",
            "token": token,
            "filename": archive.filename,
            "checked": checked,
            "compare": [(n, here.get(n, 0), checked.tables[n]) for n in names],
            "rows_here": sum(here.values()),
            "photos_here": len(backup_service.photo_files()),
        },
    )


@router.post("/restore/cancel")
def cancel(pending: Annotated[str, Form()] = ""):
    backup_service.discard_pending(pending)
    return RedirectResponse("/backup", status_code=303)


@router.post("/restore")
async def restore(
    request: Request,
    ctx: Ctx,
    archive: Annotated[UploadFile | None, File()] = None,
    pending: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    """Step two: replace the notebook with an export.

    Takes the token of a file `inspect` has already read, or — for a script,
    and for anything that still posts the old one-step form — the file
    itself. Either way it must come with `confirm=replace`.
    """
    if confirm != "replace":
        return _page(
            request,
            ctx,
            errors=["Tick the box: restoring replaces everything that is here now."],
            status_code=400,
        )

    uploaded = archive is not None and bool(archive.filename)
    if not uploaded and not pending:
        return _page(request, ctx, errors=["Choose an export to restore."], status_code=400)

    try:
        if uploaded:
            _, path = backup_service.new_pending(ctx.now)
            await _save_upload(archive, path)
        else:
            path = backup_service.pending_path(pending)
            if not path.is_file():
                raise backup_service.BackupError(
                    "That restore has expired. Choose the export again."
                )
        try:
            report = backup_service.restore(ctx.session, path, now=ctx.now)
        finally:
            path.unlink(missing_ok=True)
    except backup_service.BackupError as exc:
        ctx.session.rollback()
        return _page(request, ctx, errors=[str(exc)], status_code=400)

    log.info("restored %d rows and %d photos", report.rows, report.photos)
    done = f"{report.rows} rows and {report.photos} photos restored"
    if report.upgraded_from:
        done += ", brought up to this version's schema on the way in"
    if report.safety_copy is not None:
        done += (
            ". What was here before is saved as "
            f"{backup_service.SAFETY_DIR}/{report.safety_copy.name}"
        )
    return RedirectResponse(f"/backup?{urlencode({'done': done})}", status_code=303)
