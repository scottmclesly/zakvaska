# The desktop app

zakvaska is a small web server. The desktop app is that server, frozen into a
program that needs no Python, inside a thin native shell that gives it a
window, a tray icon and native notifications.

```
desktop/
  server.py              entry point of the frozen server
  zakvaska-server.spec   PyInstaller recipe for it
  build_server.py        runs PyInstaller; same command on macOS and Windows
  ui/index.html          the "Opening the notebook…" page shown while it starts
  src-tauri/             the shell (Rust, Tauri 2)
    src/main.rs          all of it: start the server, window, tray, alerts
    tauri.conf.json      name, identifier, what goes in the installer
```

## How it fits together

1. The shell starts `zakvaska-server` with `ZAKVASKA_DATA_DIR` set to the
   user's app-data folder, `ZAKVASKA_TZ` set from the system clock, and a port:
   8420 if nothing is using it, otherwise any free one.
2. When `/health` answers, the window goes to the server's home page. From
   there on the window is just a browser pointed at `127.0.0.1`.
3. Closing the window hides it. The server keeps running, and twice a minute
   the shell asks `/api/alerts` what is showing and raises a native
   notification for anything new. *When* an alert fires is still decided by
   the server alone, exactly as it is in Docker.
4. Quitting (tray menu) closes the server's standard input, which is its
   signal to shut down. If the shell dies any other way the same pipe closes,
   so the server never outlives it.

Nothing under `app/` knows it is running inside the desktop app, with one
exception: the pages look for `ZakvaskaDesktop` in the browser's name and, when
it is there, hide the browser's own notification offer.

## Why Tauri and PyInstaller

The app is server-rendered Python with no JavaScript build step, and that had
to stay true. So the Python is frozen as it is, and the shell is the smallest
thing that provides what a browser tab cannot: living in the tray, native
notifications, a real installer for each system. Tauri does that in about
300 lines using the system's own web view; Electron would do the same and ship
a whole browser with it. A pure-Python shell was the other candidate, and it
would have meant three more runtime dependencies, weaker notifications on an
unsigned Mac app and installers made by hand.

## Building it yourself

You need Python 3.12, Node 20 or newer, and Rust (`brew install rust`, or
<https://rustup.rs>). From the repository root:

```bash
python3.12 -m venv desktop/.venv-build
desktop/.venv-build/bin/pip install -r requirements.txt -r desktop/requirements-build.txt
desktop/.venv-build/bin/python desktop/build_server.py
```

```bash
cd desktop && npm ci && npx tauri build --bundles dmg
```

On Windows, use `--bundles nsis`. The installer is written under
`desktop/src-tauri/target/release/bundle/`.

If the Mac build stops at "couldn't unmount … Resource busy" while making the
disk image, put `CI=true` in front of the `npx` command: it skips the step
that arranges icons in the disk image's window, which is the one that trips.

To run the shell against the Python in your checkout instead of a frozen
server, point it at any program that serves on `$ZAKVASKA_PORT`:

```bash
ZAKVASKA_SERVER_BIN=/path/to/a/script npx tauri dev
```

## Where things are on a user's machine

| | macOS | Windows |
|---|---|---|
| Notebook | `~/Library/Application Support/io.github.scottmclesly.zakvaska` | `%APPDATA%\io.github.scottmclesly.zakvaska` |
| Server log | `logs/server.log` in that folder | the same |
| Shell log | `logs/app.log` in that folder | the same |

`logs/app.log` records when the server came up, each notification raised (or
why one could not be), and each file saved. It is the first thing to ask for
when someone says an alert never arrived.

## The version

`src-tauri/Cargo.toml` holds the desktop app's version. It must equal
`app.__version__` and the newest section of `CHANGELOG.md`;
`tests/test_release.py` fails if the three disagree.
