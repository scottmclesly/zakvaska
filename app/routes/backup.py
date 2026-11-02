"""Export everything, and put it back."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.background import BackgroundTask

from app.routes.deps import ViewContext, get_view_context
from app.services import backup as backup_service
from app.templates_env import render

router = APIRouter(prefix="/backup")

Ctx = Annotated[ViewContext, Depends(get_view_context)]

log = logging.getLogger("jarlog.backup")

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


@router.post("/restore")
async def restore(
    request: Request,
    ctx: Ctx,
    archive: Annotated[UploadFile | None, File()] = None,
    confirm: Annotated[str, Form()] = "",
):
    if confirm != "replace":
        return _page(
            request,
            ctx,
            errors=["Tick the box: restoring replaces everything that is here now."],
            status_code=400,
        )
    if archive is None or not archive.filename:
        return _page(request, ctx, errors=["Choose an export to restore."], status_code=400)

    handle = tempfile.NamedTemporaryFile(
        prefix="jarlog-restore-", suffix=".zip", delete=False
    )
    path = Path(handle.name)
    try:
        with handle:
            size = 0
            while chunk := await archive.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise HTTPException(
                        status_code=413, detail="That archive is too large."
                    )
                handle.write(chunk)

        try:
            report = backup_service.restore(ctx.session, path)
        except backup_service.BackupError as exc:
            ctx.session.rollback()
            return _page(request, ctx, errors=[str(exc)], status_code=400)
    finally:
        path.unlink(missing_ok=True)

    log.info("restored %d rows and %d photos", report.rows, report.photos)
    return RedirectResponse(
        f"/backup?done={report.rows} rows and {report.photos} photos restored",
        status_code=303,
    )
