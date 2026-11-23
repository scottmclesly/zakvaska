"""Bring the notebook's schema up to date, and say so when it does.

Every schema change ships with an Alembic migration (CLAUDE.md), but until
now only `setup.sh` ran them. `run.sh` did not, so a pull that added a column
met the next `./scripts/run.sh` as a hundred lines of SQLAlchemy traceback
ending in `no such column` — a startup crash, for a database that was one
`alembic upgrade head` away from being fine.

So `run.sh` calls this first. It is quiet and does nothing at all in the
usual case, where the database is already at head.

When there *is* something to do it copies the database first. This is a lab
notebook with months of feedings in it and no other backup: a migration that
goes wrong must be recoverable, and one file copy before a schema change is a
cheap way to promise that. Backups are kept beside the database, newest
`KEEP_BACKUPS` of them, so they neither pile up forever nor vanish the moment
a second migration follows the first.

Run it directly to see where things stand:

    .venv/bin/python scripts/migrate.py --check
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.config import get_settings  # noqa: E402

#: How many of the backups taken before a migration to keep.
KEEP_BACKUPS = 5

#: Written beside the database, so a restore is a `mv` and not a hunt.
BACKUP_PREFIX = "zakvaska.db.before-"

#: SQLite keeps a write-ahead log and a shared-memory index beside the
#: database. A copy without them can be an older state of the notebook than
#: the one the app last saw, which is a backup that quietly loses feedings.
SQLITE_SIDECARS = ("", "-wal", "-shm")


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    # Our own two lines say it better than alembic's five. See migrations/env.py.
    config.attributes["configure_logger"] = False
    return config


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


def migrate(*, check_only: bool = False) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    # A database still called jarlog.db is this one under its old name, and
    # it has to be adopted before anything asks what revision it is at.
    settings.adopt_legacy_db()

    config = _alembic_config()
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

    if here is not None:
        backup = _back_up(db_path)
        _say(f"==> Backing up the notebook to {backup.name}")

    _say(f"==> Migrating the notebook: {here or 'new database'} -> {head}")
    command.upgrade(config, "head")

    if here is not None:
        _prune_backups(db_path)
    return 0


if __name__ == "__main__":
    sys.exit(migrate(check_only="--check" in sys.argv[1:]))
