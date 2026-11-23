#!/usr/bin/env bash
# Start the zakvaska server on ZAKVASKA_HOST:ZAKVASKA_PORT.
#   ./scripts/run.sh                      # normal
#   ZAKVASKA_PORT=9000 ./scripts/run.sh     # environment overrides .env
#   ./scripts/run.sh --reload             # auto-reload (needs: pip install watchfiles)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "error: no .venv found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

# .env is a fallback only: anything already exported wins. `set -a; . .env`
# would do the opposite, and app/config.py uses os.environ.setdefault, so the
# shell and the app must agree on precedence.
load_env_file() {
  local file="$1" line key value
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"          # ltrim
    case "$line" in ''|'#'*) continue ;; esac
    line="${line#export }"
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    [ -n "$key" ] || continue
    value="${value#"${value%%[![:space:]]*}"}"       # ltrim
    value="${value%"${value##*[![:space:]]}"}"       # rtrim
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    if [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < "$file"
}

load_env_file "$ROOT/.env"

# Every schema change ships with a migration (CLAUDE.md), and until now only
# setup.sh ran them — so a pull that added a column met the next run.sh as a
# startup crash ending in "no such column". This is silent when there is
# nothing to do, and copies the notebook first when there is.
if ! "$ROOT/.venv/bin/python" "$ROOT/scripts/migrate.py"; then
  echo "error: could not bring the database up to date, so not starting." >&2
  echo "       the notebook is untouched; the output above says why." >&2
  exit 1
fi

HOST="${ZAKVASKA_HOST:-127.0.0.1}"
PORT="${ZAKVASKA_PORT:-8420}"

echo "==> zakvaska on http://${HOST}:${PORT}"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "    LAN access is on. On your phone, use this machine's IP:${PORT}."
fi

exec "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
  --host "$HOST" --port "$PORT" "$@"
