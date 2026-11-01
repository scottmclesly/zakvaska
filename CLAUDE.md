# jar-log — Claude Code context

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
- **Pillow** for photo thumbnails
- **pytest** + **httpx2** TestClient (starlette 1.10 deprecated plain `httpx` here)
- Installable **PWA** (manifest + minimal service worker) so a phone on the LAN can use it

## Conventions
- All runtime data lives in `JARLOG_DATA_DIR` (default `./data/`, gitignored): `jarlog.db`, `photos/`.
- Config via `.env` (commit `.env.example` only). Keys: `JARLOG_DATA_DIR`, `JARLOG_HOST`,
  `JARLOG_PORT`, `JARLOG_TZ` (default `America/New_York`).
- Store timestamps in **UTC**; display in `JARLOG_TZ`.
- Store weights in **grams**, temperatures in **°C**; display unit is a user setting, **default °F**.
- Recipes are stored as **baker's percentages** relative to total flour; grams are derived.
- Recipes are **versioned**: editing a recipe creates a new version; bakes point at a version.
- Never hard-delete jars, recipes or bakes — archive them. Lab-notebook history matters.
- Every schema change ships with an Alembic migration.
- Keep it dependency-light. Ask before adding a dependency not listed above.
- Must run on macOS (now) and a Raspberry Pi (later) with no code changes.

## Run
```
./scripts/setup.sh   # create .venv, install requirements, run migrations
./scripts/run.sh     # start on JARLOG_HOST:JARLOG_PORT (default 127.0.0.1:8420)
```

## Out of scope for v1 (planned v2 — don't build yet, but don't block them)
Rise-curve charts, back-scheduling a bake from a target time, sensor ingest API
(`POST /api/readings` for an ESP32 temp/humidity + ToF rise sensor), ntfy phone push,
Raspberry Pi systemd deployment.

The plan and acceptance checks are in `docs/TODO-v1.md`. Work through it phase by phase,
commit at the end of each phase, and stop to ask if anything is ambiguous.
