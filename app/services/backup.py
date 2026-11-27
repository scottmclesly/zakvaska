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
import re
import secrets
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import (
    DateTime,
    MetaData,
    Table,
    create_engine,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__, migrate
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
    return f"zakvaska-export-{local:%Y%m%d-%H%M}.zip"


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
        prefix="zakvaska-export-", suffix=".zip", delete=False
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
                "That zip has no manifest.json, so it is not a zakvaska export."
            ) from None
    manifest = Manifest.from_json(raw)
    if manifest.format != FORMAT_VERSION:
        raise BackupError(
            f"That export is format {manifest.format}; this zakvaska reads "
            f"format {FORMAT_VERSION}."
        )
    return manifest


def _decoders(table: Table) -> dict[str, Any]:
    """Columns that need a string turned back into a datetime."""
    return {
        column.name: column.type
        for column in table.columns
        if isinstance(column.type, (UtcDateTime, DateTime))
    }


def _decode_row(
    table: Table, row: dict[str, Any], dates: dict[str, Any], *, aware: bool = True
) -> dict[str, Any]:
    """One exported row, as values the table will take.

    `aware` is for this app's own tables, whose timestamp columns insist on
    a timezone. A table reflected from a scratch database has plain
    DateTime columns, which want the same instant as naive UTC.
    """
    if not isinstance(row, dict):
        raise BackupError(f"{table.name} in that export holds something that is not a row.")
    known = {c.name for c in table.columns}
    unknown = set(row) - known
    if unknown:
        raise BackupError(
            f"{table.name} in that export has columns this zakvaska does not "
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
            if not aware:
                value = value.astimezone(UTC).replace(tzinfo=None)
        decoded[name] = value
    return decoded


# --- Checking an archive ---------------------------------------------------
#
# Everything that can be wrong with an archive is found here, before a single
# row of the notebook is touched. `restore` then has nothing left to discover.


@dataclass(frozen=True)
class Inspection:
    """An archive that has been read right through and found to be sound."""

    manifest: Manifest
    #: Every row, decoded and at *this* schema, ready to insert.
    rows: dict[str, list[dict[str, Any]]] = field(repr=False)
    photos: int
    #: The schema the export was taken at, when it had to be brought forward.
    upgraded_from: str | None = None

    @property
    def tables(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.rows.items()}

    @property
    def row_count(self) -> int:
        return sum(self.tables.values())


def _photo_members(archive: zipfile.ZipFile) -> list[str]:
    return [
        name
        for name in archive.namelist()
        if name.startswith(f"{PHOTO_DIR}/") and not name.endswith("/")
    ]


def _check_files(archive: zipfile.ZipFile, manifest: Manifest) -> int:
    """The zip itself: nothing escaping it, nothing damaged, nothing missing."""
    members = _photo_members(archive)
    for name in members:
        parts = Path(name[len(PHOTO_DIR) + 1 :]).parts
        if not parts or ".." in parts or Path(name).is_absolute() or name.startswith("/"):
            # A zip can name ../ paths. Ours never does; a hostile one might.
            raise BackupError(f"{name} in that export points outside the archive.")
    damaged = archive.testzip()
    if damaged is not None:
        raise BackupError(
            f"{damaged} in that export is damaged; the file may not have "
            "finished downloading or copying."
        )
    if len(members) != manifest.photos:
        raise BackupError(
            f"That export should hold {manifest.photos} photo files and holds "
            f"{len(members)}, so it is incomplete."
        )
    return len(members)


def _read_tables(archive: zipfile.ZipFile) -> dict[str, list[Any]]:
    """Every json/<table>.json in the archive, parsed but not yet believed."""
    raw: dict[str, list[Any]] = {}
    for member in archive.namelist():
        if not (member.startswith(f"{JSON_DIR}/") and member.endswith(".json")):
            continue
        name = member[len(JSON_DIR) + 1 : -len(".json")]
        try:
            rows = json.loads(archive.read(member).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BackupError(f"{member} in that export is not readable JSON.") from exc
        if not isinstance(rows, list):
            raise BackupError(f"{member} in that export is not a list of rows.")
        raw[name] = rows
    return raw


def _check_tables(
    raw: dict[str, list[Any]], manifest: Manifest, known: set[str]
) -> None:
    unknown = (set(manifest.tables) | set(raw)) - known
    if unknown:
        raise BackupError(
            "That export holds tables this zakvaska does not know: "
            f"{', '.join(sorted(unknown))}."
        )
    for name, expected in manifest.tables.items():
        found = len(raw.get(name, []))
        if found != expected:
            raise BackupError(
                f"That export should hold {expected} rows of {name} and holds "
                f"{found}, so it is incomplete."
            )


def _rows_as_they_are(
    raw: dict[str, list[Any]], manifest: Manifest
) -> dict[str, list[dict[str, Any]]]:
    """An export taken at this schema: decode it and it is ready."""
    _check_tables(raw, manifest, {table.name for table in tables()})
    rows: dict[str, list[dict[str, Any]]] = {}
    for table in tables():
        dates = _decoders(table)
        rows[table.name] = [
            _decode_row(table, row, dates) for row in raw.get(table.name, [])
        ]
    return rows


def _rows_brought_forward(
    raw: dict[str, list[Any]], manifest: Manifest
) -> dict[str, list[dict[str, Any]]]:
    """An export taken at an older schema, migrated to this one.

    The export is rebuilt in a scratch database at the schema it was taken
    at, the very migrations the notebook itself went through are run over
    it, and the rows are read back out at head. That way an old backup is
    upgraded by exactly the code that upgraded the live data — there is no
    second, hand-kept idea of what each migration did. The notebook is not
    involved until the result is known to be good.
    """
    revision = manifest.alembic_revision
    assert revision is not None
    with tempfile.TemporaryDirectory(prefix="zakvaska-upgrade-") as scratch:
        url = f"sqlite+pysqlite:///{Path(scratch) / 'export.db'}"
        config = migrate.alembic_config(url)
        try:
            command.upgrade(config, revision)
            engine = create_engine(url)
            try:
                then = MetaData()
                then.reflect(engine)
                theirs = [t for t in then.sorted_tables if t.name != "alembic_version"]
                _check_tables(raw, manifest, {t.name for t in theirs})
                with engine.begin() as conn:
                    for table in theirs:
                        dates = _decoders(table)
                        found = [
                            _decode_row(table, row, dates, aware=False)
                            for row in raw.get(table.name, [])
                        ]
                        if found:
                            conn.execute(table.insert(), found)
            finally:
                engine.dispose()

            command.upgrade(config, "head")
            engine = create_engine(url)
            try:
                with engine.connect() as conn:
                    return {
                        table.name: [
                            dict(row._mapping) for row in conn.execute(select(table))
                        ]
                        for table in tables()
                    }
            finally:
                engine.dispose()
        except BackupError:
            raise
        except Exception as exc:  # a migration or a constraint said no
            raise BackupError(
                f"That export (schema {revision}) could not be brought up to "
                f"this zakvaska's schema: {_first_line(exc)}"
            ) from exc


def _first_line(exc: Exception) -> str:
    text_ = str(exc).strip().splitlines()
    return text_[0] if text_ else type(exc).__name__


def inspect(session: Session, path: Path) -> Inspection:
    """Read an archive right through and say whether it can be restored.

    Changes nothing. Raises `BackupError`, in words worth showing, for
    anything that would stop a restore or leave it half done.
    """
    manifest = read_manifest(path)
    with _open(path) as archive:
        try:
            photos = _check_files(archive, manifest)
            raw = _read_tables(archive)
        except zipfile.BadZipFile as exc:
            raise BackupError("That zip is damaged and cannot be read.") from exc

    here = alembic_revision(session)
    theirs = manifest.alembic_revision
    if theirs == here:
        return Inspection(manifest, _rows_as_they_are(raw, manifest), photos)

    known = migrate.known_revisions()
    head = known[0] if known else None
    if theirs is None or theirs not in known:
        raise BackupError(
            "That export came from a different schema "
            f"({theirs or 'unstamped'}) that this zakvaska does not know; this "
            f"database is at {here or 'unstamped'}. If it was taken with a "
            "newer zakvaska, update this one and restore it then."
        )
    if here is not None and here != head:
        raise BackupError(
            f"This notebook's own schema ({here}) is behind the app ({head}). "
            "Restart zakvaska so it can bring it up to date, then restore."
        )
    if theirs == head:
        return Inspection(manifest, _rows_as_they_are(raw, manifest), photos)
    return Inspection(
        manifest, _rows_brought_forward(raw, manifest), photos, upgraded_from=theirs
    )


# --- A copy of what is here, before it is replaced --------------------------

SAFETY_DIR = "backups"
SAFETY_PREFIX = "before-restore-"
#: Each one is a whole export, photos and all, so only a few are kept.
KEEP_SAFETY = 3


def safety_dir() -> Path:
    return get_settings().data_dir / SAFETY_DIR


def safety_copies() -> list[Path]:
    """The copies taken before earlier restores, newest first."""
    folder = safety_dir()
    if not folder.is_dir():
        return []
    return sorted(folder.glob(f"{SAFETY_PREFIX}*.zip"), reverse=True)


def save_safety_copy(session: Session, *, now: datetime | None = None) -> Path | None:
    """Export the notebook as it stands, so a restore can itself be undone.

    Returns None for an empty notebook: there is nothing to lose, and a
    first restore onto a fresh install should not leave a file behind.
    """
    if not sum(current_counts(session).values()) and not photo_files():
        return None
    now = now or utcnow()
    target = safety_dir() / f"{SAFETY_PREFIX}{now.astimezone(UTC):%Y%m%d-%H%M%S}.zip"
    write_export(target, session, now=now)
    for old in safety_copies()[KEEP_SAFETY:]:
        old.unlink(missing_ok=True)
    return target


# --- An upload waiting to be confirmed -------------------------------------
#
# Restoring is two requests: one that uploads the file and shows what is in
# it, one that says yes. The file waits here in between, named by a token.

PENDING_DIR = "restore-pending"
PENDING_MAX_AGE_S = 24 * 3600
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def pending_path(token: str) -> Path:
    if not _TOKEN.match(token or ""):
        raise BackupError("That restore has expired. Choose the export again.")
    return get_settings().data_dir / PENDING_DIR / f"{token}.zip"


def new_pending(now: datetime | None = None) -> tuple[str, Path]:
    """A token and the path to save an upload at. Sweeps out forgotten ones."""
    folder = get_settings().data_dir / PENDING_DIR
    folder.mkdir(parents=True, exist_ok=True)
    cutoff = (now or utcnow()).timestamp() - PENDING_MAX_AGE_S
    for old in folder.glob("*.zip"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    token = secrets.token_hex(16)
    return token, folder / f"{token}.zip"


def discard_pending(token: str) -> None:
    try:
        pending_path(token).unlink(missing_ok=True)
    except BackupError:
        pass


# --- Putting it back --------------------------------------------------------


@dataclass(frozen=True)
class RestoreReport:
    manifest: Manifest
    tables: dict[str, int]
    photos: int
    #: Where the notebook as it was before this restore was saved.
    safety_copy: Path | None = None
    upgraded_from: str | None = None

    @property
    def rows(self) -> int:
        return sum(self.tables.values())


def wipe(session: Session) -> None:
    """Empty every table, children before parents."""
    for table in reversed(tables()):
        session.execute(delete(table))


def restore(
    session: Session,
    path: Path,
    *,
    now: datetime | None = None,
    keep_copy: bool = True,
) -> RestoreReport:
    """Replace everything in this notebook with what the archive holds.

    The archive is checked right through first (`inspect`), and what is here
    now is exported to `data/backups/` before any of it goes. Then it is all
    or nothing: the rows go in inside one transaction, and the photos are
    only swapped in once that has worked.
    """
    checked = inspect(session, path)
    safety = save_safety_copy(session, now=now) if keep_copy else None

    try:
        wipe(session)
        for table in tables():
            rows = checked.rows.get(table.name, [])
            if rows:
                session.execute(table.insert(), rows)
        session.flush()
    except SQLAlchemyError as exc:
        session.rollback()
        raise BackupError(
            f"The rows in that export do not fit together: {_first_line(exc)}"
        ) from exc

    with _open(path) as archive:
        photos = _restore_photos(archive)

    session.commit()
    return RestoreReport(
        manifest=checked.manifest,
        tables=checked.tables,
        photos=photos,
        safety_copy=safety,
        upgraded_from=checked.upgraded_from,
    )


def _restore_photos(archive: zipfile.ZipFile) -> int:
    """Swap the photo directory for the archive's, atomically enough.

    The new files are unpacked beside the old directory and only then moved
    into place, so a half-read archive cannot leave the photos half gone.
    """
    root = get_settings().photos_dir
    members = _photo_members(archive)

    staging = Path(tempfile.mkdtemp(prefix="zakvaska-photos-", dir=root.parent))
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
