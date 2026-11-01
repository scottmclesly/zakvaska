# jar-log

A local, single-user **baking lab notebook**: sourdough starter jars, feedings,
feeding alerts, recipes (versioned, baker's %), bakes and their results, with photos.

Built to compare a homemade whole-rye starter against a purchased Soviet rye
culture (the control) on the way to a decent Borodinsky.

## Requirements

- Python 3.12 or newer
- Nothing else — no Node, no build step, no external services

## Setup

```bash
./scripts/setup.sh    # creates .venv, installs pinned deps, runs migrations
./scripts/run.sh      # http://127.0.0.1:8420
```

`setup.sh` copies `.env.example` to `.env` on first run. Both scripts are safe
to re-run.

## Configuration

Set in `.env` (see `.env.example`):

| Key | Default | Notes |
|---|---|---|
| `JARLOG_DATA_DIR` | `./data` | SQLite database and photos. Gitignored. |
| `JARLOG_HOST` | `127.0.0.1` | Use `0.0.0.0` to reach it from a phone. |
| `JARLOG_PORT` | `8420` | |
| `JARLOG_TZ` | `America/New_York` | Timestamps are stored in UTC, shown in this zone. |

## Using it from your phone

Set `JARLOG_HOST=0.0.0.0` in `.env`, restart, then open
`http://<this-machine's-IP>:8420` on a phone on the same network. It is an
installable PWA — "Add to Home Screen" gives it an icon and a standalone window.

## Development

```bash
.venv/bin/python -m pytest              # tests
.venv/bin/alembic upgrade head          # apply migrations
.venv/bin/alembic revision --autogenerate -m "what changed"
./scripts/run.sh --reload               # needs: .venv/bin/pip install watchfiles
```

`GET /health` reports database connectivity and data-dir writability.

Conventions and the stack decision live in [CLAUDE.md](CLAUDE.md); the build
plan is in [docs/TODO-v1.md](docs/TODO-v1.md).
