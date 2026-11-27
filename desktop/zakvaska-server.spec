# PyInstaller recipe for the server inside the desktop app.
#
#     python desktop/build_server.py        (which runs this)
#
# One folder, not one file: a one-file build unpacks itself to a temp
# directory on every start, which is slow, and on Windows leaves the real
# server running when its launcher is stopped.
#
# app/config.py finds alembic.ini, migrations/, templates and static files
# relative to its own location, so they are laid out here exactly as they
# are in the repository and nothing in app/ needs to know it is frozen.
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "alembic.ini"), "."),
    (str(ROOT / "migrations"), "migrations"),
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
]
binaries = []
hiddenimports = []

# Time zones: Windows has no zone database of its own.
datas += collect_data_files("tzdata")
# APScheduler finds its triggers and executors through package metadata.
datas += copy_metadata("apscheduler")
hiddenimports += collect_submodules("apscheduler")
# Uvicorn picks its loop and protocol classes by name at run time.
hiddenimports += collect_submodules("uvicorn")
# Alembic loads migrations/env.py from disk, which imports these.
hiddenimports += collect_submodules("app")
hiddenimports += ["logging.config"]
# HEIC decoding ships as a compiled library beside the package.
for package in ("pillow_heif",):
    more_datas, more_binaries, more_hidden = collect_all(package)
    datas += more_datas
    binaries += more_binaries
    hiddenimports += more_hidden

a = Analysis(
    [str(ROOT / "desktop" / "server.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "httpx2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    # Python's UTF-8 mode: every file is read as UTF-8 whatever the system's
    # code page says, as it is on the Mac and in the container.
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name="zakvaska-server",
    # A console program on purpose: the shell starts it with no window and
    # sends its output to a log file. Built windowless, Python would have
    # no stdout at all and uvicorn's logging would fail on start.
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="zakvaska-server", upx=False)
