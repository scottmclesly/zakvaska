#!/usr/bin/env bash
# Snapshot the whole notebook: the SQLite file plus the photos, as one
# .tar.gz. Safe to run while jar-log is serving — the database is copied
# through SQLite's online-backup API, not read off the disk underneath it.
#
#   ./scripts/backup.sh                 # into ./backups
#   ./scripts/backup.sh /Volumes/stick  # somewhere else
#   ./scripts/backup.sh --keep 14       # and prune to the newest 14
#
# To put one back: stop jar-log, then untar it over the data directory.
#   tar -xzf backups/jarlog-backup-20261101-1930.tar.gz -C data
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

DEST="$ROOT/backups"
KEEP=""

while [ $# -gt 0 ]; do
  case "$1" in
    --keep)
      KEEP="${2:-}"
      [ -n "$KEEP" ] || { echo "error: --keep needs a number" >&2; exit 2; }
      shift 2
      ;;
    -h|--help)
      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
      exit 0
      ;;
    *)
      DEST="$1"
      shift
      ;;
  esac
done

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "error: no .venv found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

PY="$ROOT/.venv/bin/python"

# Ask the app where its data lives, so .env and JARLOG_DATA_DIR are honoured
# here exactly as they are at runtime.
DATA_DIR="$("$PY" -c 'from app.config import get_settings; print(get_settings().data_dir)')"

if [ ! -f "$DATA_DIR/jarlog.db" ]; then
  echo "error: no database at $DATA_DIR/jarlog.db — nothing to back up." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/jarlog-backup-XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "==> Copying the database (online backup)"
"$PY" - "$DATA_DIR/jarlog.db" "$STAGE/jarlog.db" <<'PYEOF'
import sqlite3
import sys

source_path, target_path = sys.argv[1], sys.argv[2]
# A plain file copy can catch the database mid-write, and with WAL on it
# would miss anything still in the -wal file. This API takes a consistent
# snapshot of a live database and checkpoints it into the copy.
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
target.close()
source.close()
PYEOF

if [ -d "$DATA_DIR/photos" ]; then
  echo "==> Copying the photos"
  cp -R "$DATA_DIR/photos" "$STAGE/photos"
else
  mkdir -p "$STAGE/photos"
fi

ARCHIVE="$DEST/jarlog-backup-$STAMP.tar.gz"
echo "==> Writing $ARCHIVE"
tar -czf "$ARCHIVE" -C "$STAGE" jarlog.db photos

if [ -n "$KEEP" ]; then
  # Newest first, drop everything past the Nth.
  # shellcheck disable=SC2012
  ls -t "$DEST"/jarlog-backup-*.tar.gz 2>/dev/null \
    | tail -n "+$((KEEP + 1))" \
    | while IFS= read -r old; do
        echo "==> Pruning $(basename "$old")"
        rm -f "$old"
      done
fi

SIZE="$(du -h "$ARCHIVE" | cut -f1 | tr -d ' ')"
echo
echo "Done: $ARCHIVE ($SIZE)"
