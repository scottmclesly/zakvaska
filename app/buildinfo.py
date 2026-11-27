"""Which build of the app this is.

The version (`app.__version__`) is the number in the changelog and moves by
hand. The build is the commit this copy is running from: how many commits
there are behind it, and its short hash — so "is the Pi on what I just
pushed?" has an answer on the About page.

Read from git once, at startup. A copy with no git beside it (an unpacked
archive, say) simply has no build to report, and nothing here may stop the
app from starting.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Build:
    #: Commits up to and including this one. Goes up by one per commit on a
    #: line of history, which is what makes it read as a build number.
    number: int
    #: The commit's short hash.
    commit: str
    #: The day it was committed, as YYYY-MM-DD.
    date: str

    @property
    def label(self) -> str:
        return f"build {self.number}"


def _git(*args: str) -> str:
    done = subprocess.run(
        ("git", "-C", str(ROOT), *args),
        capture_output=True, text=True, timeout=5, check=True,
    )
    return done.stdout.strip()


@lru_cache(maxsize=1)
def build() -> Build | None:
    try:
        return Build(
            number=int(_git("rev-list", "--count", "HEAD")),
            commit=_git("rev-parse", "--short", "HEAD"),
            date=_git("log", "-1", "--format=%cs"),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
