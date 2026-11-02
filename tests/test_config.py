from pathlib import Path

import pytest

from app.config import (
    DEFAULTS,
    PROJECT_ROOT,
    Settings,
    build_settings,
    parse_dotenv,
)


def test_parse_dotenv_handles_comments_blanks_quotes_and_export():
    parsed = parse_dotenv(
        "\n".join(
            [
                "# a comment",
                "",
                "ZAKVASKA_PORT=8420",
                "  ZAKVASKA_HOST = 0.0.0.0  ",
                'ZAKVASKA_TZ="Europe/Riga"',
                "export ZAKVASKA_DATA_DIR='/tmp/x'",
                "NOT_A_PAIR",
            ]
        )
    )

    assert parsed == {
        "ZAKVASKA_PORT": "8420",
        "ZAKVASKA_HOST": "0.0.0.0",
        "ZAKVASKA_TZ": "Europe/Riga",
        "ZAKVASKA_DATA_DIR": "/tmp/x",
    }


def test_environment_wins_over_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAKVASKA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ZAKVASKA_HOST", "0.0.0.0")
    monkeypatch.setenv("ZAKVASKA_PORT", "9999")
    monkeypatch.setenv("ZAKVASKA_TZ", "Europe/Riga")

    settings = build_settings()

    assert settings.data_dir == tmp_path
    assert settings.host == "0.0.0.0"
    assert settings.port == 9999
    assert settings.tz_name == "Europe/Riga"


def test_relative_data_dir_resolves_against_the_project_root(monkeypatch):
    monkeypatch.setenv("ZAKVASKA_DATA_DIR", "./data")

    assert build_settings().data_dir == PROJECT_ROOT / "data"


def test_a_bad_timezone_fails_at_startup_not_at_render_time(monkeypatch):
    monkeypatch.setenv("ZAKVASKA_TZ", "Mars/Olympus_Mons")

    with pytest.raises(Exception):
        build_settings()


def test_derived_paths(tmp_path):
    settings = Settings(data_dir=tmp_path, host="127.0.0.1", port=8420, tz_name="UTC")

    assert settings.db_path == tmp_path / "zakvaska.db"
    assert settings.photos_dir == tmp_path / "photos"
    assert settings.db_url.endswith(f"{tmp_path}/zakvaska.db")


def test_ensure_dirs_creates_the_data_and_photos_dirs(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "fresh", host="127.0.0.1", port=8420, tz_name="UTC"
    )

    settings.ensure_dirs()

    assert settings.data_dir.is_dir()
    assert settings.photos_dir.is_dir()


def test_env_example_documents_every_supported_key():
    # Derived from DEFAULTS rather than a hand-written list, so adding a
    # setting without documenting it fails here.
    documented = set(parse_dotenv(Path(PROJECT_ROOT / ".env.example").read_text()))

    assert documented == set(DEFAULTS)


def test_the_alert_scheduler_is_on_by_default(monkeypatch):
    monkeypatch.delenv("ZAKVASKA_SCHEDULER", raising=False)
    monkeypatch.delenv("JARLOG_SCHEDULER", raising=False)

    assert build_settings().scheduler_enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_the_alert_scheduler_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv("ZAKVASKA_SCHEDULER", value)

    assert build_settings().scheduler_enabled is False


# --- The old name ----------------------------------------------------------
#
# This app was called jar-log until it was renamed. An .env written then is
# still a working .env: losing someone's configuration over a rename would be
# a poor trade for a tidier prefix.


def test_the_old_env_keys_still_work(monkeypatch, tmp_path):
    # An installed copy has a .env naming the new keys, and that file would
    # supply them before the fallback is ever reached. This is about the
    # fallback, so take the file out of it.
    monkeypatch.setattr("app.config.load_dotenv", lambda path=None: {})
    monkeypatch.delenv("ZAKVASKA_DATA_DIR", raising=False)
    monkeypatch.delenv("ZAKVASKA_PORT", raising=False)
    monkeypatch.setenv("JARLOG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARLOG_PORT", "9001")

    settings = build_settings()

    assert settings.data_dir == tmp_path
    assert settings.port == 9001


def test_the_new_key_wins_when_both_are_set(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.load_dotenv", lambda path=None: {})
    monkeypatch.setenv("JARLOG_PORT", "9001")
    monkeypatch.setenv("ZAKVASKA_PORT", "9002")

    assert build_settings().port == 9002


def test_an_old_database_is_adopted_under_the_new_name(tmp_path):
    settings = Settings(
        data_dir=tmp_path, host="127.0.0.1", port=8420, tz_name="UTC"
    )
    settings.ensure_dirs()
    (tmp_path / "jarlog.db").write_bytes(b"pretend sqlite")
    (tmp_path / "jarlog.db-wal").write_bytes(b"pretend wal")

    assert settings.adopt_legacy_db() is True

    assert settings.db_path.read_bytes() == b"pretend sqlite"
    assert (tmp_path / "zakvaska.db-wal").exists()
    assert not (tmp_path / "jarlog.db").exists()


def test_a_new_database_is_never_overwritten_by_an_old_one(tmp_path):
    """If both exist, the one in use wins — a rename must not lose data."""
    settings = Settings(
        data_dir=tmp_path, host="127.0.0.1", port=8420, tz_name="UTC"
    )
    settings.ensure_dirs()
    (tmp_path / "jarlog.db").write_bytes(b"old")
    settings.db_path.write_bytes(b"current")

    assert settings.adopt_legacy_db() is False

    assert settings.db_path.read_bytes() == b"current"
    assert (tmp_path / "jarlog.db").read_bytes() == b"old"


def test_nothing_happens_when_there_is_no_old_database(tmp_path):
    settings = Settings(
        data_dir=tmp_path, host="127.0.0.1", port=8420, tz_name="UTC"
    )
    settings.ensure_dirs()

    assert settings.adopt_legacy_db() is False
