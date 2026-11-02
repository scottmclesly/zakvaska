"""Exporting everything, and putting it back.

The export is deliberately boring: one zip holding the rows as JSON, the
same rows as CSV, and the photo files. JSON is what restores; the CSV is
for reading a table in a spreadsheet years from now, when this app may be
long gone. That second audience is the point of a lab notebook.

Rows are read straight from the tables rather than through the ORM, so a
table added later is exported without anyone remembering to list it here.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.models import Base
from app.models.base import utcnow
from app.models.types import UtcDateTime

# Bump this if the layout inside the zip ever changes shape.
FORMAT_VERSION = 1

MANIFEST_NAME = "manifest.json"
JSON_DIR = "json"
CSV_DIR = "csv"
PHOTO_DIR = "photos"


class BackupError(ValueError):
    """Something about an archive is wrong, in words worth showing."""


@dataclass(frozen=True)
class Manifest:
    format: int
    app_version: str
    alembic_revision: str | None
    exported_at: datetime
    tables: dict[str, int]
    photos: int

    @property
    def rows(self) -> int:
        return sum(self.tables.values())

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": self.format,
                "app_version": self.app_version,
                "alembic_revision": self.alembic_revision,
                "exported_at": self.exported_at.isoformat(),
                "tables": self.tables,
                "photos": self.photos,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> Manifest:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackupError("The archive's manifest is not readable JSON.") from exc
        if not isinstance(data, dict):
            raise BackupError("The archive's manifest is not an object.")
        try:
            return cls(
                format=int(data["format"]),
                app_version=str(data.get("app_version", "?")),
                alembic_revision=data.get("alembic_revision"),
                exported_at=datetime.fromisoformat(data["exported_at"]),
                tables={str(k): int(v) for k, v in dict(data["tables"]).items()},
                photos=int(data.get("photos", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError("The archive's manifest is missing fields.") from exc


# --- Reading the database --------------------------------------------------


def tables() -> list[Table]:
    """Every table, parents before children, which is also insert order."""
    return list(Base.metadata.sorted_tables)


def alembic_revision(session: Session) -> str | None:
    """Which migration the database is on, or None if it was never stamped.

    Tests build the schema with create_all and never stamp it; a restore
    between two such databases is still a match, which is what matters.
    """
    try:
        return session.execute(text("select version_num from alembic_version")).scalar()
    except Exception:
        return None


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def rows_for(session: Session, table: Table) -> list[dict[str, Any]]:
    result = session.execute(select(table))
    return [
        {name: _encode(value) for name, value in zip(result.keys(), row, strict=True)}
        for row in result
    ]


def _csv_bytes(table: Table, rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    columns = [c.name for c in table.columns]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if v is None else v for k, v in row.items()})
    return buffer.getvalue().encode("utf-8")


def photo_files() -> list[Path]:
    root = get_settings().photos_dir
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


# --- Writing an archive ----------------------------------------------------


def export_filename(now: datetime | None = None) -> str:
    local = (now or utcnow()).astimezone(get_settings().tz)
    return f"jarlog-export-{local:%Y%m%d-%H%M}.zip"


def write_export(destination: Path, session: Session, *, now: datetime | None = None) -> Manifest:
    """Write the whole notebook to `destination` and return what went in."""
    now = now or utcnow()
    counts: dict[str, int] = {}
    shots = photo_files()
    photos_root = get_settings().photos_dir

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for table in tables():
            rows = rows_for(session, table)
            counts[table.name] = len(rows)
            archive.writestr(
                f"{JSON_DIR}/{table.name}.json",
                json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False),
            )
            archive.writestr(f"{CSV_DIR}/{table.name}.csv", _csv_bytes(table, rows))

        for shot in shots:
            # Photos are already JPEG; compressing them again buys nothing.
            archive.write(
                shot,
                f"{PHOTO_DIR}/{shot.relative_to(photos_root).as_posix()}",
                compress_type=zipfile.ZIP_STORED,
            )

        manifest = Manifest(
            format=FORMAT_VERSION,
            app_version=__version__,
            alembic_revision=alembic_revision(session),
            exported_at=now,
            tables=counts,
            photos=len(shots),
        )
        archive.writestr(MANIFEST_NAME, manifest.to_json())

    return manifest


def export_to_temp(session: Session, *, now: datetime | None = None) -> tuple[Path, Manifest]:
    """Build an export in a temp file, for handing straight to a download."""
    handle = tempfile.NamedTemporaryFile(
        prefix="jarlog-export-", suffix=".zip", delete=False
    )
    handle.close()
    path = Path(handle.name)
    try:
        manifest = write_export(path, session, now=now)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path, manifest


# --- Reading an archive back -----------------------------------------------


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise BackupError("That file is not a zip archive.") from exc


def read_manifest(path: Path) -> Manifest:
    with _open(path) as archive:
        try:
            raw = archive.read(MANIFEST_NAME).decode("utf-8")
        except KeyError:
            raise BackupError(
                "That zip has no manifest.json, so it is not a jar-log export."
            ) from None
    manifest = Manifest.from_json(raw)
    if manifest.format != FORMAT_VERSION:
        raise BackupError(
            f"That export is format {manifest.format}; this jar-log reads "
            f"format {FORMAT_VERSION}."
        )
    return manifest


def _check_schema(session: Session, manifest: Manifest) -> None:
    here = alembic_revision(session)
    if manifest.alembic_revision != here:
        raise BackupError(
            "That export came from a different schema "
            f"({manifest.alembic_revision or 'unstamped'}); this database is at "
            f"{here or 'unstamped'}. Run the migrations that match it first."
        )


def _decoders(table: Table) -> dict[str, Any]:
    """Columns that need a string turned back into a datetime."""
    return {
        column.name: column.type
        for column in table.columns
        if isinstance(column.type, UtcDateTime)
    }


def _decode_row(table: Table, row: dict[str, Any], dates: dict[str, Any]) -> dict[str, Any]:
    known = {c.name for c in table.columns}
    unknown = set(row) - known
    if unknown:
        raise BackupError(
            f"{table.name} in that export has columns this jar-log does not "
            f"know: {', '.join(sorted(unknown))}."
        )
    decoded: dict[str, Any] = {}
    for name in known:
        value = row.get(name)
        if value is not None and name in dates:
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise BackupError(
                    f"{table.name}.{name} has a timestamp that will not parse: {value!r}"
                ) from exc
            value = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        decoded[name] = value
    return decoded


@dataclass(frozen=True)
class RestoreReport:
    manifest: Manifest
    tables: dict[str, int]
    photos: int

    @property
    def rows(self) -> int:
        return sum(self.tables.values())


def wipe(session: Session) -> None:
    """Empty every table, children before parents."""
    for table in reversed(tables()):
        session.execute(delete(table))


def restore(session: Session, path: Path) -> RestoreReport:
    """Replace everything in this notebook with what the archive holds.

    All or nothing: the rows go in inside one transaction, and the photos
    are only swapped in once that has worked.
    """
    manifest = read_manifest(path)
    _check_schema(session, manifest)

    known = {table.name for table in tables()}
    unknown = set(manifest.tables) - known
    if unknown:
        raise BackupError(
            "That export holds tables this jar-log does not know: "
            f"{', '.join(sorted(unknown))}."
        )

    counts: dict[str, int] = {}
    with _open(path) as archive:
        names = set(archive.namelist())
        wipe(session)
        for table in tables():
            member = f"{JSON_DIR}/{table.name}.json"
            if member not in names:
                counts[table.name] = 0
                continue
            try:
                rows = json.loads(archive.read(member).decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise BackupError(f"{member} in that export is not readable JSON.") from exc
            if not isinstance(rows, list):
                raise BackupError(f"{member} in that export is not a list of rows.")
            dates = _decoders(table)
            if rows:
                session.execute(
                    table.insert(), [_decode_row(table, row, dates) for row in rows]
                )
            counts[table.name] = len(rows)

        session.flush()
        photos = _restore_photos(archive)

    session.commit()
    return RestoreReport(manifest=manifest, tables=counts, photos=photos)


def _restore_photos(archive: zipfile.ZipFile) -> int:
    """Swap the photo directory for the archive's, atomically enough.

    The new files are unpacked beside the old directory and only then moved
    into place, so a half-read archive cannot leave the photos half gone.
    """
    root = get_settings().photos_dir
    members = [
        name
        for name in archive.namelist()
        if name.startswith(f"{PHOTO_DIR}/") and not name.endswith("/")
    ]

    staging = Path(tempfile.mkdtemp(prefix="jarlog-photos-", dir=root.parent))
    try:
        for name in members:
            relative = name[len(PHOTO_DIR) + 1 :]
            target = (staging / relative).resolve()
            if not target.is_relative_to(staging.resolve()):
                # A zip can name ../ paths. Ours never does; a hostile one might.
                raise BackupError(f"{name} in that export points outside the archive.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)

        old = root.with_name(root.name + ".replaced")
        shutil.rmtree(old, ignore_errors=True)
        if root.exists():
            root.rename(old)
        staging.rename(root)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return len(members)


# --- What the page shows ---------------------------------------------------


def current_counts(session: Session) -> dict[str, int]:
    """Row counts for every table, for the backup page."""
    return {
        table.name: session.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        for table in tables()
    }


def photo_bytes() -> int:
    return sum(p.stat().st_size for p in photo_files())
