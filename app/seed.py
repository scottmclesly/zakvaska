"""Seed reference data: the bread maker's programs and the recipe library.

    python -m app.seed --dry-run     # say what would happen, change nothing
    python -m app.seed               # do it

Add-only and safe to run twice: see app/services/seeding.py.
"""

from __future__ import annotations

import argparse
import sys

from app.db import get_sessionmaker
from app.logging_config import setup_logging
from app.services import seeding


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be added, without writing anything",
    )
    args = parser.parse_args(argv)

    setup_logging()
    with get_sessionmaker()() as session:
        report = seeding.seed_all(session, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    for line in report.lines():
        print(line)
    if args.dry_run:
        print("\nDry run: nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
