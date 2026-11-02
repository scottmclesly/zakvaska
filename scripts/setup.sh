#!/usr/bin/env bash
# Create .venv, install pinned dependencies, run migrations.
# Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

MIN_MAJOR=3
MIN_MINOR=12

find_python() {
  # Honour an explicit override first, then prefer the oldest supported
  # interpreter: it is the one every pinned wheel is known to build on.
  local candidates=("${PYTHON:-}" python3.12 python3.13 python3.14 python3)
  for py in "${candidates[@]}"; do
    [ -n "$py" ] || continue
    command -v "$py" >/dev/null 2>&1 || continue
    if "$py" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

if ! PY="$(find_python)"; then
  echo "error: zakvaska needs Python ${MIN_MAJOR}.${MIN_MINOR} or newer." >&2
  echo "       Found: $(python3 --version 2>&1 || echo 'no python3 on PATH')" >&2
  echo "       Install it (macOS: brew install python@3.12) or set PYTHON=/path/to/python3.12" >&2
  exit 1
fi

echo "==> Using $PY ($("$PY" --version 2>&1))"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "==> Creating .venv"
  "$PY" -m venv "$ROOT/.venv"
else
  echo "==> Reusing existing .venv"
fi

VENV_PY="$ROOT/.venv/bin/python"

echo "==> Installing dependencies"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r "$ROOT/requirements.txt"

if [ ! -f "$ROOT/.env" ]; then
  echo "==> Creating .env from .env.example"
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

echo "==> Running migrations"
"$ROOT/.venv/bin/alembic" upgrade head

echo
echo "Done. Start it with:  ./scripts/run.sh"
