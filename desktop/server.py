"""The server as the desktop app runs it: one frozen program, no Python needed.

PyInstaller freezes this file (see zakvaska-server.spec) and the Tauri shell
in src-tauri/ starts the result, telling it where to keep the notebook and
which port to listen on through the same ZAKVASKA_* variables everything
else uses. Nothing in app/ knows or cares that it is running this way.

    zakvaska-server --exit-with-parent

`--exit-with-parent` is how the server avoids outliving the app. The shell
holds this process's standard input open and never writes to it; when the
shell goes away, however it goes, the pipe closes, the read below returns,
and the server shuts down. No process ids to track, and the same on macOS
and Windows.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading


def _follow_parent(server) -> None:
    def wait() -> None:
        try:
            # The raw descriptor, not sys.stdin: a thread parked inside
            # Python's buffered reader makes the interpreter abort on exit.
            fd = sys.stdin.fileno()
            while os.read(fd, 4096):
                pass
        except (OSError, ValueError):
            return  # no usable stdin: nothing to follow, so stay up
        server.should_exit = True
        # A graceful stop normally takes well under a second. If it hangs,
        # leave anyway: SQLite's log makes that safe for the notebook.
        threading.Timer(5.0, lambda: os._exit(0)).start()

    threading.Thread(target=wait, name="follow-parent", daemon=True).start()


def main() -> int:
    multiprocessing.freeze_support()

    import uvicorn

    from app.config import get_settings
    from app.main import app

    settings = get_settings()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            use_colors=False,
            access_log=False,
        )
    )
    if "--exit-with-parent" in sys.argv[1:] and sys.stdin is not None:
        _follow_parent(server)
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
