"""run.sh must agree with app/config.py: the environment beats .env."""

from __future__ import annotations

import os
import subprocess
import tarfile

import pytest

from app.config import PROJECT_ROOT

# Echo the resolved values instead of starting uvicorn.
PROBE = r'''
set -euo pipefail
cd "$1"
load_env_file() { :; }
# shellcheck disable=SC1090
eval "$(sed -n '/^load_env_file() {/,/^}/p' scripts/run.sh)"
load_env_file "$2"
echo "HOST=${ZAKVASKA_HOST:-127.0.0.1}"
echo "PORT=${ZAKVASKA_PORT:-8420}"
'''


def _resolve(env_text: str, tmp_path, **overrides) -> dict[str, str]:
    env_file = tmp_path / ".env"
    env_file.write_text(env_text)

    env = {k: v for k, v in os.environ.items() if not k.startswith("ZAKVASKA_")}
    env.update(overrides)

    result = subprocess.run(
        ["bash", "-c", PROBE, "probe", str(PROJECT_ROOT), str(env_file)],
        capture_output=True, text=True, env=env, check=True,
    )
    return dict(
        line.split("=", 1) for line in result.stdout.strip().splitlines()
    )


def test_env_file_supplies_values_when_nothing_is_exported(tmp_path):
    resolved = _resolve("ZAKVASKA_HOST=0.0.0.0\nZAKVASKA_PORT=8420\n", tmp_path)

    assert resolved == {"HOST": "0.0.0.0", "PORT": "8420"}


def test_exported_value_beats_the_env_file(tmp_path):
    resolved = _resolve(
        "ZAKVASKA_PORT=8420\n", tmp_path, ZAKVASKA_PORT="8421"
    )

    assert resolved["PORT"] == "8421"


def test_comments_blanks_quotes_and_export_are_handled(tmp_path):
    resolved = _resolve(
        '# comment\n\nexport ZAKVASKA_HOST="0.0.0.0"\n  ZAKVASKA_PORT = 9000 \n',
        tmp_path,
    )

    assert resolved == {"HOST": "0.0.0.0", "PORT": "9000"}


def test_defaults_apply_with_no_env_file_at_all(tmp_path):
    resolved = _resolve("", tmp_path)

    assert resolved == {"HOST": "127.0.0.1", "PORT": "8420"}


# --- backup.sh -------------------------------------------------------------

BACKUP_SH = PROJECT_ROOT / "scripts" / "backup.sh"


def _notebook(tmp_path):
    """A data dir with a real database and a photo file in it."""
    import sqlite3

    data_dir = tmp_path / "data"
    (data_dir / "photos" / "2026" / "03").mkdir(parents=True)
    (data_dir / "photos" / "2026" / "03" / "crumb.jpg").write_bytes(b"pretend jpeg")

    db = sqlite3.connect(data_dir / "zakvaska.db")
    db.execute("create table jar (id integer primary key, name text)")
    db.execute("insert into jar (name) values ('Homemade rye')")
    db.commit()
    db.close()
    return data_dir


def _run_backup(data_dir, dest, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZAKVASKA_")}
    env["ZAKVASKA_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        ["bash", str(BACKUP_SH), str(dest), *args],
        capture_output=True, text=True, env=env, check=True,
    )


def _archives(dest):
    return sorted(dest.glob("zakvaska-backup-*.tar.gz"))


@pytest.mark.skipif(
    not (PROJECT_ROOT / ".venv" / "bin" / "python").exists(),
    reason="backup.sh runs the project's own venv",
)
class TestBackupScript:
    def test_it_writes_an_archive_with_the_database_and_the_photos(self, tmp_path):
        data_dir = _notebook(tmp_path)
        dest = tmp_path / "backups"

        _run_backup(data_dir, dest)

        archives = _archives(dest)
        assert len(archives) == 1
        with tarfile.open(archives[0]) as tar:
            names = tar.getnames()
        assert "zakvaska.db" in names
        assert "photos/2026/03/crumb.jpg" in names

    def test_the_copied_database_is_readable_and_complete(self, tmp_path):
        """The online-backup API, not a file copy, so a live database is fine."""
        import sqlite3

        data_dir = _notebook(tmp_path)
        dest = tmp_path / "backups"
        _run_backup(data_dir, dest)

        out = tmp_path / "unpacked"
        with tarfile.open(_archives(dest)[0]) as tar:
            tar.extractall(out, filter="data")

        rows = sqlite3.connect(out / "zakvaska.db").execute(
            "select name from jar"
        ).fetchall()
        assert rows == [("Homemade rye",)]

    def test_keep_prunes_the_oldest(self, tmp_path):
        data_dir = _notebook(tmp_path)
        dest = tmp_path / "backups"
        dest.mkdir()
        for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
            (dest / f"zakvaska-backup-{stamp}.tar.gz").write_bytes(b"old")

        _run_backup(data_dir, dest, "--keep", "2")

        assert len(_archives(dest)) == 2

    def test_it_refuses_a_data_dir_with_no_database(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("ZAKVASKA_")}
        env["ZAKVASKA_DATA_DIR"] = str(empty)

        result = subprocess.run(
            ["bash", str(BACKUP_SH), str(tmp_path / "backups")],
            capture_output=True, text=True, env=env,
        )

        assert result.returncode != 0
        assert "nothing to back up" in result.stderr
