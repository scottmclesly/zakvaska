"""Exporting the notebook and reading it back.

The last class is Phase 6's acceptance check from docs/TODO-v1.md: export,
wipe the data dir, restore, and find everything where it was.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.enums import IngredientRole, JarOrigin, PhotoOwner, RecipeCategory
from app.services import backup as backup_service
from app.services import jars as jar_service
from app.services import photos as photo_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec
from tests.test_photos_service import make_image


def seed(session) -> dict[str, object]:
    """A small but complete notebook: jar, feeding, observation, recipe, photo."""
    jar = jar_service.create_jar(
        session, name="Homemade rye", origin=JarOrigin.HOMEMADE,
        flour_type="whole rye", notes="started from scratch",
    )
    session.commit()
    feeding = jar_service.log_feeding(
        session, jar, starter_g=20, flour_g=40, water_g=40, ambient_temp_c=21.5
    )
    recipe = recipe_service.create_recipe(
        session, name="Borodinsky", category=RecipeCategory.RYE,
        ingredients=[
            IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
        ],
        stages=[StageSpec("scald (zavarka)", duration_min=240, temp_c=65.0)],
    )
    photo = photo_service.attach(
        session, owner_type=PhotoOwner.JAR, owner_id=jar.id,
        data=make_image(), caption="day three",
    )
    session.commit()
    return {"jar": jar, "feeding": feeding, "recipe": recipe, "photo": photo}


def export(session, tmp_path, name="export.zip") -> Path:
    path = tmp_path / name
    backup_service.write_export(path, session)
    return path


def members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def read_json(path: Path, member: str):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(member).decode("utf-8"))


def rewrite(path: Path, target: Path, changes: dict[str, bytes | None]) -> Path:
    """Copy an archive, replacing or dropping named members."""
    with zipfile.ZipFile(path) as old, zipfile.ZipFile(target, "w") as new:
        for item in old.namelist():
            if item in changes:
                continue
            new.writestr(item, old.read(item))
        for item, data in changes.items():
            if data is not None:
                new.writestr(item, data)
    return target


class TestWhatGoesIn:
    def test_every_table_is_written_as_json_and_csv(self, session, tmp_path):
        seed(session)
        inside = members(export(session, tmp_path))

        for table in backup_service.tables():
            assert f"json/{table.name}.json" in inside
            assert f"csv/{table.name}.csv" in inside

    def test_the_manifest_counts_the_rows(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)

        manifest = backup_service.read_manifest(path)
        assert manifest.tables["jar"] == 1
        assert manifest.tables["feeding"] == 1
        assert manifest.tables["recipe_ingredient"] == 2
        assert manifest.photos == 2  # the photo and its thumbnail
        assert manifest.rows == sum(manifest.tables.values())

    def test_the_rows_are_really_in_there(self, session, tmp_path):
        seed(session)
        rows = read_json(export(session, tmp_path), "json/jar.json")

        assert len(rows) == 1
        assert rows[0]["name"] == "Homemade rye"
        assert rows[0]["flour_type"] == "whole rye"

    def test_timestamps_are_written_as_utc(self, session, tmp_path):
        seed(session)
        rows = read_json(export(session, tmp_path), "json/feeding.json")

        when = datetime.fromisoformat(rows[0]["fed_at"])
        assert when.tzinfo is not None
        assert when.utcoffset().total_seconds() == 0

    def test_the_csv_is_readable_on_its_own(self, session, tmp_path):
        """The CSV is for whoever opens this in ten years without the app."""
        seed(session)
        with zipfile.ZipFile(export(session, tmp_path)) as archive:
            text = archive.read("csv/jar.csv").decode("utf-8")

        rows = list(csv.DictReader(io.StringIO(text)))
        assert len(rows) == 1
        assert rows[0]["name"] == "Homemade rye"
        assert rows[0]["culture_name"] == ""  # None becomes empty, not "None"

    def test_the_photo_files_come_too(self, session, tmp_path):
        made = seed(session)
        photo = made["photo"]

        inside = members(export(session, tmp_path))
        assert f"photos/{photo.path}" in inside
        assert f"photos/{photo.thumb_path}" in inside

    def test_an_empty_notebook_still_exports(self, session, tmp_path):
        manifest = backup_service.read_manifest(export(session, tmp_path))

        assert manifest.rows == 0
        assert manifest.photos == 0

    def test_the_filename_says_when(self, session):
        when = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        # 12:00 UTC is 08:00 in New York, and the name is local.
        assert backup_service.export_filename(when) == "zakvaska-export-20260315-0800.zip"


class TestRoundTrip:
    def test_the_rows_come_back(self, session, tmp_path):
        seed(session)
        before = backup_service.current_counts(session)
        path = export(session, tmp_path)

        backup_service.wipe(session)
        session.commit()
        assert sum(backup_service.current_counts(session).values()) == 0

        report = backup_service.restore(session, path)

        assert backup_service.current_counts(session) == before
        assert report.rows == sum(before.values())

    def test_the_values_come_back_unchanged(self, session, tmp_path):
        made = seed(session)
        jar_id = made["jar"].id
        fed_at = made["feeding"].fed_at
        path = export(session, tmp_path)

        backup_service.wipe(session)
        session.commit()
        backup_service.restore(session, path)

        from app.models.feeding import Feeding
        from app.models.jar import Jar

        jar = session.get(Jar, jar_id)
        assert jar.name == "Homemade rye"
        assert jar.origin is JarOrigin.HOMEMADE
        assert jar.notes == "started from scratch"

        restored = session.get(Feeding, 1)
        assert restored.fed_at == fed_at
        assert restored.fed_at.tzinfo is not None
        assert restored.ambient_temp_c == pytest.approx(21.5)

    def test_the_photo_files_come_back(self, session, tmp_path):
        made = seed(session)
        relative = made["photo"].path
        original = photo_service.absolute(relative).read_bytes()
        path = export(session, tmp_path)

        backup_service.wipe(session)
        session.commit()
        photo_service.absolute(relative).unlink()

        report = backup_service.restore(session, path)

        assert report.photos == 2
        assert photo_service.absolute(relative).read_bytes() == original

    def test_restoring_replaces_what_is_here(self, session, tmp_path):
        """Not a merge: the archive wins, whole."""
        path = export(session, tmp_path)  # an empty notebook
        seed(session)
        assert backup_service.current_counts(session)["jar"] == 1

        backup_service.restore(session, path)

        assert backup_service.current_counts(session)["jar"] == 0

    def test_a_photo_that_is_not_in_the_archive_goes(self, session, tmp_path):
        path = export(session, tmp_path)  # no photos yet
        made = seed(session)
        stale = photo_service.absolute(made["photo"].path)
        assert stale.is_file()

        backup_service.restore(session, path)

        assert not stale.exists()

    def test_restoring_twice_is_not_twice_the_rows(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        before = backup_service.current_counts(session)

        backup_service.restore(session, path)
        backup_service.restore(session, path)

        assert backup_service.current_counts(session) == before


class TestRefusals:
    def test_something_that_is_not_a_zip(self, tmp_path):
        junk = tmp_path / "notes.txt"
        junk.write_text("this is not an export")

        with pytest.raises(backup_service.BackupError, match="not a zip"):
            backup_service.read_manifest(junk)

    def test_a_zip_with_no_manifest(self, tmp_path):
        path = tmp_path / "other.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("hello.txt", "hi")

        with pytest.raises(backup_service.BackupError, match="no manifest"):
            backup_service.read_manifest(path)

    def test_an_export_from_a_future_format(self, session, tmp_path):
        path = export(session, tmp_path)
        manifest = json.loads(zipfile.ZipFile(path).read("manifest.json"))
        manifest["format"] = 99
        broken = rewrite(
            path, tmp_path / "future.zip",
            {"manifest.json": json.dumps(manifest).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="format 99"):
            backup_service.read_manifest(broken)

    def test_an_export_from_another_schema(self, session, tmp_path):
        path = export(session, tmp_path)
        manifest = json.loads(zipfile.ZipFile(path).read("manifest.json"))
        manifest["alembic_revision"] = "deadbeef1234"
        broken = rewrite(
            path, tmp_path / "older.zip",
            {"manifest.json": json.dumps(manifest).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="different schema"):
            backup_service.restore(session, broken)

    def test_a_table_this_version_does_not_have(self, session, tmp_path):
        path = export(session, tmp_path)
        manifest = json.loads(zipfile.ZipFile(path).read("manifest.json"))
        manifest["tables"]["sensor_reading"] = 3
        broken = rewrite(
            path, tmp_path / "newer.zip",
            {"manifest.json": json.dumps(manifest).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="sensor_reading"):
            backup_service.restore(session, broken)

    def test_a_column_this_version_does_not_have(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        rows = read_json(path, "json/jar.json")
        rows[0]["rise_sensor_id"] = 7
        broken = rewrite(
            path, tmp_path / "widened.zip",
            {"json/jar.json": json.dumps(rows).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="rise_sensor_id"):
            backup_service.restore(session, broken)

    def test_a_timestamp_that_will_not_parse(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        rows = read_json(path, "json/jar.json")
        rows[0]["created_at"] = "whenever"
        broken = rewrite(
            path, tmp_path / "bad-date.zip",
            {"json/jar.json": json.dumps(rows).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="will not parse"):
            backup_service.restore(session, broken)

    def test_a_photo_path_that_escapes_the_archive(self, session, tmp_path):
        path = export(session, tmp_path)
        broken = rewrite(
            path, tmp_path / "escape.zip",
            {"photos/../../stolen.jpg": b"not really a photo"},
        )

        with pytest.raises(backup_service.BackupError, match="outside the archive"):
            backup_service.restore(session, broken)

    def test_a_failed_restore_leaves_the_photos_alone(self, session, tmp_path):
        made = seed(session)
        kept = photo_service.absolute(made["photo"].path)
        path = export(session, tmp_path)
        rows = read_json(path, "json/jar.json")
        rows[0]["created_at"] = "whenever"
        broken = rewrite(
            path, tmp_path / "bad-date.zip",
            {"json/jar.json": json.dumps(rows).encode()},
        )

        with pytest.raises(backup_service.BackupError):
            backup_service.restore(session, broken)
        session.rollback()

        assert kept.is_file()


class TestThePage:
    def test_it_shows_what_is_here(self, client, session):
        seed(session)

        page = client.get("/backup")

        assert page.status_code == 200
        assert "What is here" in page.text
        assert "Download everything" in page.text

    def test_an_empty_notebook_says_so(self, client):
        assert "Nothing logged yet" in client.get("/backup").text

    def test_every_page_links_to_it(self, client):
        assert '/backup' in client.get("/").text

    def test_downloading(self, client, session):
        seed(session)

        response = client.get("/backup/export")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "zakvaska-export-" in response.headers["content-disposition"]
        assert zipfile.ZipFile(io.BytesIO(response.content)).read("manifest.json")

    def test_restoring_through_the_form(self, client, session, tmp_path):
        seed(session)
        archive = client.get("/backup/export").content
        backup_service.wipe(session)
        session.commit()

        response = client.post(
            "/backup/restore",
            data={"confirm": "replace"},
            files={"archive": ("export.zip", archive, "application/zip")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "restored" in response.headers["location"]
        assert backup_service.current_counts(session)["jar"] == 1

    def test_restoring_needs_the_box_ticked(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        backup_service.wipe(session)
        session.commit()

        response = client.post(
            "/backup/restore",
            files={"archive": ("export.zip", archive, "application/zip")},
        )

        assert response.status_code == 400
        assert "Tick the box" in response.text
        assert backup_service.current_counts(session)["jar"] == 0

    def test_restoring_needs_a_file(self, client):
        response = client.post("/backup/restore", data={"confirm": "replace"})

        assert response.status_code == 400
        assert "Choose an export" in response.text

    def test_a_file_that_is_not_an_export(self, client):
        response = client.post(
            "/backup/restore",
            data={"confirm": "replace"},
            files={"archive": ("notes.txt", b"not an export", "application/zip")},
        )

        assert response.status_code == 400
        assert "not a zip" in response.text


class TestPhaseSixAcceptance:
    """Export, wipe the data dir, restore: everything comes back."""

    def test_the_whole_round_trip(self, client, session, data_dir, tmp_path):
        made = seed(session)
        jar_id = made["jar"].id
        photo_path = made["photo"].path
        original = photo_service.absolute(photo_path).read_bytes()
        before = backup_service.current_counts(session)

        archive = client.get("/backup/export").content
        held = tmp_path / "zakvaska-export.zip"
        held.write_bytes(archive)

        # Wipe the data dir: every row, every photo file.
        backup_service.wipe(session)
        session.commit()
        for stale in backup_service.photo_files():
            stale.unlink()
        assert sum(backup_service.current_counts(session).values()) == 0
        assert backup_service.photo_files() == []

        response = client.post(
            "/backup/restore",
            data={"confirm": "replace"},
            files={"archive": (held.name, held.read_bytes(), "application/zip")},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Restored" in response.text

        assert backup_service.current_counts(session) == before

        from app.models.jar import Jar

        jar = session.get(Jar, jar_id)
        assert jar.name == "Homemade rye"
        assert "Homemade rye" in client.get(f"/jars/{jar_id}").text

        back = photo_service.absolute(photo_path)
        assert back.is_file()
        assert back.read_bytes() == original
        assert back.is_relative_to(data_dir.resolve())
        assert client.get(f"/photos/{made['photo'].id}/file").status_code == 200
