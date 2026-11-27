#!/usr/bin/env python3
"""Freeze the server for the desktop app. Same command on macOS and Windows.

    python desktop/build_server.py

Needs requirements.txt and desktop/requirements-build.txt installed in the
Python that runs it. Writes desktop/dist/zakvaska-server/, which the Tauri
build (desktop/src-tauri/tauri.conf.json) copies into the app as `server/`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    done = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--distpath", str(HERE / "dist"),
            "--workpath", str(HERE / "build"),
            str(HERE / "zakvaska-server.spec"),
        ],
        cwd=HERE.parent,
    )
    if done.returncode == 0:
        print(f"\nServer frozen into {HERE / 'dist' / 'zakvaska-server'}")
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
