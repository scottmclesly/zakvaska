"""run.sh must agree with app/config.py: the environment beats .env."""

from __future__ import annotations

import os
import subprocess

from app.config import PROJECT_ROOT

# Echo the resolved values instead of starting uvicorn.
PROBE = r'''
set -euo pipefail
cd "$1"
load_env_file() { :; }
# shellcheck disable=SC1090
eval "$(sed -n '/^load_env_file() {/,/^}/p' scripts/run.sh)"
load_env_file "$2"
echo "HOST=${JARLOG_HOST:-127.0.0.1}"
echo "PORT=${JARLOG_PORT:-8420}"
'''


def _resolve(env_text: str, tmp_path, **overrides) -> dict[str, str]:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text)

    env = {k: v for k, v in os.environ.items() if not k.startswith("JARLOG_")}
    env.update(overrides)

    result = subprocess.run(
        ["bash", "-c", PROBE, "probe", str(PROJECT_ROOT), str(env_file)],
        capture_output=True, text=True, env=env, check=True,
    )
    return dict(
        line.split("=", 1) for line in result.stdout.strip().splitlines()
    )


def test_env_file_supplies_values_when_nothing_is_exported(tmp_path):
    resolved = _resolve("JARLOG_HOST=0.0.0.0\nJARLOG_PORT=8420\n", tmp_path)

    assert resolved == {"HOST": "0.0.0.0", "PORT": "8420"}


def test_exported_value_beats_the_env_file(tmp_path):
    resolved = _resolve(
        "JARLOG_PORT=8420\n", tmp_path, JARLOG_PORT="8421"
    )

    assert resolved["PORT"] == "8421"


def test_comments_blanks_quotes_and_export_are_handled(tmp_path):
    resolved = _resolve(
        '# comment\n\nexport JARLOG_HOST="0.0.0.0"\n  JARLOG_PORT = 9000 \n',
        tmp_path,
    )

    assert resolved == {"HOST": "0.0.0.0", "PORT": "9000"}


def test_defaults_apply_with_no_env_file_at_all(tmp_path):
    resolved = _resolve("", tmp_path)

    assert resolved == {"HOST": "127.0.0.1", "PORT": "8420"}
