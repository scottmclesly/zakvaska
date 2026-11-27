#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md, as the release notes.

    python scripts/release_notes.py 1.0.0

The release workflow calls this, so what is written in the changelog is
what appears on the GitHub Release. Exits 1 if the version has no section,
which stops a release that nobody wrote notes for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

INSTALL = """
---

**Installing.** Desktop: download the file for your computer below and see
[the README](https://github.com/scottmclesly/zakvaska#install) for the one
extra click an unsigned app needs. Docker: `docker compose pull && docker
compose up -d`, or run the install script again. Updating never touches the
notebook.
"""


def section(version: str, text: str) -> str | None:
    """The body under `## [version]`, up to the next `## [` heading."""
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    body = section(argv[1].removeprefix("v"), CHANGELOG.read_text(encoding="utf-8"))
    if not body:
        print(f"error: CHANGELOG.md has no section for {argv[1]}", file=sys.stderr)
        return 1
    print(body)
    print(INSTALL)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
