#!/usr/bin/env bash
# Seed the bread maker's programs and the reference recipes.
#   ./scripts/seed.sh --dry-run   # say what would happen, change nothing
#   ./scripts/seed.sh             # do it
# Add-only: nothing already in the notebook is changed or removed.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "error: no .venv found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

exec .venv/bin/python -m app.seed "$@"
