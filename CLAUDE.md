# zakvaska — Claude Code context

A local, single-user **baking lab notebook**: sourdough starter jars, feedings, feeding alerts,
recipes (versioned, baker's %), bakes and their results, with photos. Owner: Scott McLeslie.

## Why it exists
Scott is building toward Russian **Borodinsky** (dark rye). He runs two rye starter jars side by
side as an experiment: his own homemade whole-rye starter and a purchased Soviet rye culture as
the **control**. He bakes in a cast-iron pot in the oven and in a **West Bend bread maker**.
Comparing jars and iterating recipes is the point, so the data must be structured, not free text.

## Stack (decided — do not swap without asking)
- Python 3.12+, **FastAPI** + Uvicorn (+ `python-multipart`, which FastAPI and
  starlette both require for *any* form parsing, not only file uploads)
- **SQLite** via **SQLAlchemy 2.0** (typed ORM), **Alembic** for migrations
- Server-rendered **Jinja2** templates + **HTMX** (vendored into `static/`, no CDN, no JS build step)
- **APScheduler** (in-process) for alerts
- **Pillow** (+ **pillow-heif**, so iPhone HEIC opens) for photo renditions and thumbnails
- **pytest** + **httpx2** TestClient (starlette 1.10 deprecated plain `httpx` here)
- **tzdata** (data only): Windows and slim containers have no zone database
- Build-time only, never imported by `app/`: **PyInstaller** (freezes the server) and
  **Tauri 2** (Rust shell; its CLI comes from npm in `desktop/`). The app itself still
  has no JS build step.
- Installable **PWA** (manifest + minimal service worker) so a phone on the LAN can use it

## Conventions
- All runtime data lives in `ZAKVASKA_DATA_DIR` (default `./data/`, gitignored): `zakvaska.db`, `photos/`.
- Config via `.env` (commit `.env.example` only). Keys: `ZAKVASKA_DATA_DIR`, `ZAKVASKA_HOST`,
  `ZAKVASKA_PORT`, `ZAKVASKA_TZ` (default `America/New_York`). The old `JARLOG_*` keys are
  still read as a fallback, and a `jarlog.db` is renamed to `zakvaska.db` on first open.
- Store timestamps in **UTC**; display in `ZAKVASKA_TZ`.
- **A rhythm is on the wall clock; a duration is real time.** Planned feeds step by
  whole cycles on the local clock (`plan.cycles_on`), as recurring busy blocks do, so
  eight-and-eight stays eight-and-eight across a daylight-saving change. Rise curves,
  bake steps and the preheat lead are elapsed time and never gain or lose the hour.
  `tests/test_alert_timing.py` holds both halves to it.
- Store weights in **grams**, temperatures in **°C**. Both have a display setting, picked by
  name on `/settings` (`POST /settings/units`): temperature **default °F**, weight **default
  grams**, the others US cups/spoons and oz/lb. Volume readings use the per-ingredient
  densities in `app/services/measures.py` and are approximate by nature; never store or
  round-trip through them.
- The display unit is also the **entry** unit: every weight field goes through
  `measures.parse_quantity` (`forms.req_weight` / `opt_weight`), so a bare number is read in
  the unit on display and a written-out unit ("250 g", "1 lb 2 oz", "1 ½ cups") wins over it.
  Totals use `parse_total` / `measure_total`, which take `flour=`: a **flour** total reads in
  cups at the generic flour density, a **dough** total never does — a mixture has no density
  anyone measures. Pass `flour=True` at every flour-total site, label included, so the box and
  the words over it agree about how a bare number will be read.
- Recipes are stored as **baker's percentages** relative to total flour; grams are derived.
  A recipe may be *typed* as amounts instead: the percentages come from them and the flour
  weight they came to is kept on the version as `batch_flour_g`, which is what lets a recipe
  written in cups read back in cups. Null means it was given as percentages.
- Recipes are **versioned**: editing a recipe creates a new version; bakes point at a version.
- **Hints are data.** Every tip the app gives a baker is a `Hint` in
  `app/data/hints.py`; `app/services/hints.py` decides which step, stage or page
  it belongs to (a bake's step by `step_key`, a recipe's stage by name). Templates
  include `partials/hints.html` and never carry hint wording themselves. A hint is
  one or two lines, never blocks a step, and is dismissed for good with "Got it":
  the dismissed ids are one row in the settings table (`hints_dismissed`).
  Explainer drawings are inline SVG in `templates/partials/explainers/`, coloured
  only through the stylesheet's `.ex-*` classes so they follow the theme.
- The drawn jar moves by one value, `Life` (`services/jars.life_of`: active, hungry,
  overdue, resting), carried as `life-*` on the SVG. Motion is CSS keyframes on
  `transform`/`opacity` only, all inside `prefers-reduced-motion: no-preference`.
- Folds and the lid are **not steps**, for the reason the preheat is not: they are
  numbers on the step they happen during (`fold_sets`/`fold_every_min` on a bulk
  ferment, `lid_off_after_min` on a pot's single bake step), copied from the settings
  when a bake is written down. `followalong.fold_moments` / `lid_off_moment` work the
  times out from when the step really began; each has its own `AlertKind`.
- Never hard-delete jars, recipes or bakes — archive them. Lab-notebook history matters.
- Every schema change ships with an Alembic migration.
- Keep it dependency-light. Ask before adding a dependency not listed above.
- Must run on macOS (now) and a Raspberry Pi (later) with no code changes.

## Run
```
./scripts/setup.sh   # create .venv, install requirements, run migrations
./scripts/run.sh     # migrate if needed, then start on ZAKVASKA_HOST:ZAKVASKA_PORT
```
The runner is `app/migrate.py`. The app calls it in its own startup, so uvicorn
started directly migrates too, and `scripts/migrate.py` (which both scripts call)
is the same thing from the command line: silent when the schema is already at
head, and it copies the notebook to `data/zakvaska.db.before-<stamp>` before it
changes anything. `--check` reports without touching anything. A database with
tables but no schema version is refused and left untouched. `ZAKVASKA_MIGRATE=0`
turns the startup run off; that is for the test suite, whose schema comes from
the models.

Restore (Settings → Backup) is two steps: `POST /backup/inspect` reads the file
right through and shows it against what is here, `POST /backup/restore` replaces.
An export from an older schema is rebuilt in a scratch database and brought
forward by the real migrations, and the notebook as it stood is exported to
`data/backups/before-restore-<stamp>.zip` first.

## Shipping (v1.0.0 onwards)
Two install paths, both built by `.github/workflows/release.yml` on a `v*.*.*` tag.
`docs/RELEASING.md` is the checklist; `docs/SIGNING.md` is what to add for signing.
- **Docker**: `Dockerfile` + `docker-compose.yml` must stay zero-config: every
  `${VAR}` in the compose file has a default. Data is the named volume
  `zakvaska-data` at `/data`. `scripts/docker-install.sh` is installer and updater.
  `requirements.txt` is runtime only; test tools live in `requirements-dev.txt`.
- **Desktop**: `desktop/` (see its README). The shell starts the frozen server with
  the same `ZAKVASKA_*` variables, so nothing under `app/` may assume how it was
  started. The one thing pages know is the `ZakvaskaDesktop` mark in the browser
  name (`is-desktop` on `<html>`), used only to hide the browser-notification offer.
  A link the window should save (an export) needs nothing special; a link that
  leaves `127.0.0.1` opens in the real browser.
- **The server never calls out.** The update check is the browser asking GitHub,
  on a button press. Keep it that way.
- **One version, three places**: `app/__init__.py`, `desktop/src-tauri/Cargo.toml`,
  and the top section of `CHANGELOG.md`, which is also the release notes.
  `tests/test_release.py` holds them together.
- Keep `alembic.ini` plain ASCII: it is read in the system's encoding, and on
  Windows and in the frozen server that is not UTF-8.
- `app/services/demo.py` fills an **empty** notebook only, through the services.

## Out of scope for v1 (planned v2 — don't build yet, but don't block them)
Back-scheduling a bake from a target time, sensor ingest API
(`POST /api/readings` for an ESP32 temp/humidity + ToF rise sensor), ntfy phone push.
(The Pi is served by the Docker image now, not a systemd unit.)

Rise-curve charts were pulled forward out of that list. Plots are drawn
server-side: `app/services/charts.py` works out the coordinates and the Jinja
partials emit inline SVG. No chart library — that would mean a JS build step.

The original v1 plan and its acceptance checks are in `docs/dev/TODO-v1.md` (all done).
Commit at the end of each piece of work, and stop to ask if anything is ambiguous.
