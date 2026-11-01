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
                "JARLOG_PORT=8420",
                "  JARLOG_HOST = 0.0.0.0  ",
                'JARLOG_TZ="Europe/Riga"',
                "export JARLOG_DATA_DIR='/tmp/x'",
                "NOT_A_PAIR",
            ]
        )
    )

    assert parsed == {
        "JARLOG_PORT": "8420",
        "JARLOG_HOST": "0.0.0.0",
        "JARLOG_TZ": "Europe/Riga",
        "JARLOG_DATA_DIR": "/tmp/x",
    }


def test_environment_wins_over_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("JARLOG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JARLOG_HOST", "0.0.0.0")
    monkeypatch.setenv("JARLOG_PORT", "9999")
    monkeypatch.setenv("JARLOG_TZ", "Europe/Riga")

    settings = build_settings()

    assert settings.data_dir == tmp_path
    assert settings.host == "0.0.0.0"
    assert settings.port == 9999
    assert settings.tz_name == "Europe/Riga"


def test_relative_data_dir_resolves_against_the_project_root(monkeypatch):
    monkeypatch.setenv("JARLOG_DATA_DIR", "./data")

    assert build_settings().data_dir == PROJECT_ROOT / "data"


def test_a_bad_timezone_fails_at_startup_not_at_render_time(monkeypatch):
    monkeypatch.setenv("JARLOG_TZ", "Mars/Olympus_Mons")

    with pytest.raises(Exception):
        build_settings()


def test_derived_paths(tmp_path):
    settings = Settings(data_dir=tmp_path, host="127.0.0.1", port=8420, tz_name="UTC")

    assert settings.db_path == tmp_path / "jarlog.db"
    assert settings.photos_dir == tmp_path / "photos"
    assert settings.db_url.endswith(f"{tmp_path}/jarlog.db")


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
    monkeypatch.delenv("JARLOG_SCHEDULER", raising=False)

    assert build_settings().scheduler_enabled is True


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_the_alert_scheduler_can_be_switched_off(monkeypatch, value):
    monkeypatch.setenv("JARLOG_SCHEDULER", value)

    assert build_settings().scheduler_enabled is False
