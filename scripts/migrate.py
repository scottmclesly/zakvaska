"""Bring the notebook's schema up to date, and say so when it does.

The runner itself is `app/migrate.py`, which the app also calls as it
starts. This is the same thing from the command line, for `setup.sh` and
`run.sh` and for asking where things stand:

    .venv/bin/python scripts/migrate.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.migrate import (  # noqa: E402, F401 — re-exported for callers
    BACKUP_PREFIX,
    KEEP_BACKUPS,
    SchemaError,
    migrate,
)

if __name__ == "__main__":
    try:
        sys.exit(migrate(check_only="--check" in sys.argv[1:]))
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
