"""Bring the notebook's schema up to date, and say so when it does.

The schema version is Alembic's: one row in `alembic_version`, naming the
migration the database is at. This module is the runner. It is called in two
places, and they are the only two ways the app comes up:

- the app's own startup (`app.main.lifespan`), so starting uvicorn directly,
  from an editor's launch config or a systemd unit on the Pi, migrates
  exactly as `run.sh` does;
- `scripts/migrate.py`, which `setup.sh` and `run.sh` call, and which is
  also how to ask where things stand (`--check`).

It is quiet and does nothing at all in the usual case, where the database is
already at head.

When there *is* something to do it copies the database first. This is a lab
notebook with months of feedings in it: a migration that goes wrong must be
recoverable, and one file copy before a schema change is a cheap way to
promise that. Backups are kept beside the database, newest `KEEP_BACKUPS` of
them, so they neither pile up forever nor vanish the moment a second
migration follows the first.

An update never wipes the notebook. Migrations only ever move forward from
the recorded version; a database this cannot place is refused and left
untouched rather than rebuilt.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.config import PROJECT_ROOT, get_settings

#: How many of the backups taken before a migration to keep.
KEEP_BACKUPS = 5

#: Written beside the database, so a restore is a `mv` and not a hunt.
BACKUP_PREFIX = "zakvaska.db.before-"

#: SQLite keeps a write-ahead log and a shared-memory index beside the
#: database. A copy without them can be an older state of the notebook than
#: the one the app last saw, which is a backup that quietly loses feedings.
SQLITE_SIDECARS = ("", "-wal", "-shm")


def alembic_config(db_url: str | None = None) -> Config:
    """Alembic, pointed at the notebook, or at `db_url` when one is given."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # Our own two lines say it better than alembic's five. See migrations/env.py.
    config.attributes["configure_logger"] = False
    if db_url is not None:
        config.attributes["db_url"] = db_url
    return config


def known_revisions() -> list[str]:
    """Every schema version this copy of the app knows, newest first."""
    script = ScriptDirectory.from_config(alembic_config())
    return [revision.revision for revision in script.walk_revisions()]


def _say(message: str) -> None:
    """Flushed, because alembic writes to stderr and we write to stdout: a
    pipe buffers one and not the other, and the lines come out shuffled."""
    print(message, flush=True)


def _stamped(db_path: Path) -> str | None:
    """The revision this database is at, or None if it has never been one."""
    if not db_path.exists():
        return None
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def _unversioned_tables(db_path: Path) -> list[str]:
    """Tables in a database that carries no schema version at all."""
    if not db_path.exists():
        return []
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return sorted(
                name
                for name in inspect(conn).get_table_names()
                if name != "alembic_version"
            )
    finally:
        engine.dispose()


def _head(config: Config) -> str | None:
    return ScriptDirectory.from_config(config).get_current_head()


def _back_up(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_path.with_name(f"{BACKUP_PREFIX}{stamp}")
    for suffix in SQLITE_SIDECARS:
        beside = db_path.with_name(db_path.name + suffix)
        if beside.exists():
            shutil.copy2(beside, target.with_name(target.name + suffix))
    return target


def _prune_backups(db_path: Path) -> None:
    kept = sorted(
        db_path.parent.glob(f"{BACKUP_PREFIX}*"),
        key=lambda one: one.name,
        reverse=True,
    )
    # Group by backup, so a copy's -wal and -shm go with it.
    stems: list[str] = []
    for one in kept:
        stem = one.name.split("-wal")[0].split("-shm")[0]
        if stem not in stems:
            stems.append(stem)
    for stem in stems[KEEP_BACKUPS:]:
        for suffix in SQLITE_SIDECARS:
            old = db_path.with_name(stem + suffix)
            if old.exists():
                old.unlink()


class SchemaError(RuntimeError):
    """The database cannot be brought up to date, in words worth showing."""


def migrate(*, check_only: bool = False) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    # A database still called jarlog.db is this one under its old name, and
    # it has to be adopted before anything asks what revision it is at.
    settings.adopt_legacy_db()

    config = alembic_config()
    db_path = settings.db_path
    here, head = _stamped(db_path), _head(config)

    if here == head:
        if check_only:
            _say(f"up to date ({head})")
        return 0

    if check_only:
        where = here or "no schema yet"
        _say(f"behind: {where} -> {head}")
        return 1

    if here is None and (found := _unversioned_tables(db_path)):
        # Tables, but no record of which schema they are. Building the
        # schema over the top of them could only fail halfway or write over
        # something, so this stops and leaves the file exactly as it is.
        raise SchemaError(
            f"{db_path.name} has tables ({', '.join(found[:4])}"
            f"{', …' if len(found) > 4 else ''}) but no schema version, so "
            "it cannot be migrated safely. Nothing was changed. If it was "
            "built by this app at the current schema, mark it with "
            "`alembic stamp head`; otherwise restore an export into a new, "
            "empty data directory."
        )

    if here is not None:
        backup = _back_up(db_path)
        _say(f"==> Backing up the notebook to {backup.name}")

    _say(f"==> Migrating the notebook: {here or 'new database'} -> {head}")
    command.upgrade(config, "head")

    if here is not None:
        _prune_backups(db_path)
    return 0
