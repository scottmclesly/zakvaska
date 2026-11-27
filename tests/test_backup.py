"""Exporting the notebook and reading it back.

The last class is Phase 6's acceptance check from docs/TODO-v1.md: export,
wipe the data dir, restore, and find everything where it was.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.enums import (
    IngredientRole,
    JarOrigin,
    JarState,
    PhotoOwner,
    RecipeCategory,
)
from app.models.feeding import Feeding
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
        assert manifest.photos == 3  # the original, the rendition, the thumbnail
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

        assert report.photos == 3
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

    def test_it_is_two_steps_from_anywhere(self, client):
        """Backup is a tab of Settings now, not a link at the foot of every
        page: Settings is in the header everywhere, and the tab is on it."""
        assert 'href="/settings"' in client.get("/").text
        tabs = client.get("/settings").text.split('<nav class="tabs"')[1].split("</nav>")[0]
        assert 'href="/backup"' in tabs

    def test_it_is_a_tab_of_settings(self, client):
        page = client.get("/backup").text
        tabs = page.split('<nav class="tabs"')[1].split("</nav>")[0]

        assert "<h1>Settings</h1>" in page
        assert tabs.split('class="tab is-current"')[1].split("</a>")[0].rstrip().endswith("Backup")
        # And the header marks Settings as where you are.
        marked = page.split(' is-here"')[1].split("</a>")[0]
        assert "<span>Settings</span>" in marked

    def test_the_footer_no_longer_links_to_it(self, client):
        footer = client.get("/").text.split('<footer class="footer">')[1].split("</footer>")[0]
        assert "/backup" not in footer
        assert 'href="/about"' in footer

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


# --- Checking before replacing ------------------------------------------


class TestInspecting:
    """`inspect` reads an archive right through and changes nothing."""

    def test_it_says_what_is_in_the_file(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)

        checked = backup_service.inspect(session, path)

        assert checked.tables["jar"] == 1
        assert checked.tables["feeding"] == 1
        assert checked.photos == len(backup_service.photo_files())
        assert checked.upgraded_from is None

    def test_it_leaves_the_notebook_alone(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        before = backup_service.current_counts(session)

        backup_service.inspect(session, path)

        assert backup_service.current_counts(session) == before

    def test_a_file_with_rows_missing(self, session, tmp_path):
        """A truncated table must not quietly restore as a smaller notebook."""
        seed(session)
        path = export(session, tmp_path)
        short = rewrite(path, tmp_path / "short.zip", {"json/feeding.json": b"[]"})

        with pytest.raises(backup_service.BackupError, match="incomplete"):
            backup_service.inspect(session, short)

    def test_a_file_with_a_photo_missing(self, session, tmp_path):
        made = seed(session)
        path = export(session, tmp_path)
        gone = next(m for m in members(path) if m.startswith("photos/"))
        short = rewrite(path, tmp_path / "short.zip", {gone: None})
        assert made["photo"] is not None

        with pytest.raises(backup_service.BackupError, match="photo files"):
            backup_service.inspect(session, short)

    def test_rows_that_point_at_nothing(self, session, tmp_path):
        """A feeding for a jar that is not in the file: refused, and what was
        here is still here afterwards."""
        seed(session)
        path = export(session, tmp_path)
        rows = read_json(path, "json/feeding.json")
        rows[0]["jar_id"] = 999
        broken = rewrite(
            path, tmp_path / "orphan.zip",
            {"json/feeding.json": json.dumps(rows).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="do not fit together"):
            backup_service.restore(session, broken)

        assert backup_service.current_counts(session)["jar"] == 1
        assert backup_service.current_counts(session)["feeding"] == 1


class TestTheSafetyCopy:
    """What was here is exported before a restore replaces it."""

    @pytest.fixture(autouse=True)
    def _no_copies_yet(self):
        shutil.rmtree(backup_service.safety_dir(), ignore_errors=True)
        yield
        shutil.rmtree(backup_service.safety_dir(), ignore_errors=True)

    def test_a_restore_leaves_one(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)

        report = backup_service.restore(session, path)

        assert report.safety_copy is not None
        assert report.safety_copy.is_file()
        assert backup_service.safety_copies() == [report.safety_copy]

    def test_it_holds_what_was_here_not_what_came_in(self, session, tmp_path):
        seed(session)
        incoming = export(session, tmp_path)
        jar_service.create_jar(session, name="Second jar", origin=JarOrigin.HOMEMADE)
        session.commit()

        report = backup_service.restore(session, incoming)

        assert backup_service.current_counts(session)["jar"] == 1
        names = {row["name"] for row in read_json(report.safety_copy, "json/jar.json")}
        assert names == {"Homemade rye", "Second jar"}

    def test_it_can_itself_be_restored(self, session, tmp_path):
        """Which is what makes a restore undoable."""
        seed(session)
        incoming = export(session, tmp_path)
        jar_service.create_jar(session, name="Second jar", origin=JarOrigin.HOMEMADE)
        session.commit()
        report = backup_service.restore(session, incoming)

        backup_service.restore(session, report.safety_copy)

        assert backup_service.current_counts(session)["jar"] == 2

    def test_an_empty_notebook_leaves_none(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        backup_service.wipe(session)
        session.commit()
        shutil.rmtree(get_settings().photos_dir)

        report = backup_service.restore(session, path)

        assert report.safety_copy is None
        assert backup_service.safety_copies() == []

    def test_a_refused_file_leaves_none(self, session, tmp_path):
        seed(session)
        (tmp_path / "junk.zip").write_bytes(b"nope")

        with pytest.raises(backup_service.BackupError):
            backup_service.restore(session, tmp_path / "junk.zip")

        assert backup_service.safety_copies() == []

    def test_only_the_newest_few_are_kept(self, session, tmp_path):
        seed(session)
        path = export(session, tmp_path)
        start = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

        for n in range(backup_service.KEEP_SAFETY + 2):
            backup_service.restore(session, path, now=start + timedelta(minutes=n))

        kept = backup_service.safety_copies()
        assert len(kept) == backup_service.KEEP_SAFETY
        assert kept[0].name.endswith("120400.zip")


# --- An export from an older zakvaska -----------------------------------

#: The revision before the one that added jar.cap_color.
ONE_BEHIND = "6360163c0825"


def old_export(tmp_path, *, revision=ONE_BEHIND) -> Path:
    """An export as an older zakvaska would have written it: no cap_color."""
    jar = {
        "id": 1, "name": "Old Rye", "origin": "HOMEMADE", "state": "ACTIVE",
        "culture_name": None, "flour_type": "whole rye",
        "feed_interval_room_h": 12.0, "feed_interval_fridge_h": 168.0,
        "is_control": False, "archived": False, "notes": None, "parent_jar_id": None,
        "created_at": "2026-01-01T09:30:00+00:00",
    }
    feeding = {
        "id": 1, "jar_id": 1, "fed_at": "2026-01-02T13:00:00+00:00",
        "starter_g": 20.0, "flour_g": 40.0, "water_g": 40.0,
        "created_at": "2026-01-02T13:00:05+00:00",
    }
    path = tmp_path / "old-export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("json/jar.json", json.dumps([jar]))
        archive.writestr("json/feeding.json", json.dumps([feeding]))
        archive.writestr(
            "manifest.json",
            json.dumps({
                "format": 1, "app_version": "0.9.0",
                "alembic_revision": revision,
                "exported_at": "2026-01-03T00:00:00+00:00",
                "tables": {"jar": 1, "feeding": 1}, "photos": 0,
            }),
        )
    return path


class TestAnExportFromAnOlderSchema:
    """A backup taken before an update must still restore after it."""

    def test_it_is_accepted_and_says_where_it_came_from(self, session, tmp_path):
        checked = backup_service.inspect(session, old_export(tmp_path))

        assert checked.upgraded_from == ONE_BEHIND
        assert checked.tables["jar"] == 1

    def test_the_rows_arrive_with_the_new_columns(self, session, tmp_path):
        backup_service.restore(session, old_export(tmp_path))

        (jar,) = jar_service.list_jars(session)
        assert jar.name == "Old Rye"
        assert jar.cap_color is None
        assert jar.state is JarState.ACTIVE

    def test_the_timestamps_arrive_as_the_same_instants(self, session, tmp_path):
        backup_service.restore(session, old_export(tmp_path))

        (jar,) = jar_service.list_jars(session)
        assert jar.created_at == datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
        feeding = session.scalars(select(Feeding)).one()
        assert feeding.fed_at == datetime(2026, 1, 2, 13, 0, tzinfo=UTC)

    def test_the_app_runs_on_what_came_in(self, client, session, tmp_path):
        backup_service.restore(session, old_export(tmp_path))

        assert "Old Rye" in client.get("/").text

    def test_a_revision_nobody_has_heard_of_is_still_refused(self, session, tmp_path):
        """Most likely an export from a *newer* zakvaska than this one."""
        path = old_export(tmp_path, revision="deadbeef1234")

        with pytest.raises(backup_service.BackupError, match="newer zakvaska"):
            backup_service.inspect(session, path)

    def test_a_column_the_old_schema_never_had_is_refused(self, session, tmp_path):
        path = old_export(tmp_path)
        rows = read_json(path, "json/jar.json")
        rows[0]["cap_color"] = "#ff0000"
        broken = rewrite(
            path, tmp_path / "anachronism.zip",
            {"json/jar.json": json.dumps(rows).encode()},
        )

        with pytest.raises(backup_service.BackupError, match="cap_color"):
            backup_service.inspect(session, broken)


# --- The two steps, through the browser ---------------------------------


class TestRestoringInTwoSteps:
    def _inspect(self, client, archive):
        return client.post(
            "/backup/inspect",
            files={"archive": ("export.zip", archive, "application/zip")},
        )

    def _token(self, response) -> str:
        match = re.search(r'name="pending" value="([0-9a-f]{32})"', response.text)
        assert match, response.text[:600]
        return match.group(1)

    def test_the_form_on_the_page_checks_first(self, client):
        body = client.get("/backup").text

        assert 'action="/backup/inspect"' in body
        assert 'action="/backup/restore"' not in body

    def test_checking_shows_both_sides_and_changes_nothing(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        jar_service.create_jar(session, name="Second jar", origin=JarOrigin.HOMEMADE)
        session.commit()

        response = self._inspect(client, archive)

        assert response.status_code == 200
        assert "Here now" in response.text and "In the file" in response.text
        assert "Replace everything with this file" in response.text
        assert backup_service.current_counts(session)["jar"] == 2

    def test_saying_yes_restores(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        jar_service.create_jar(session, name="Second jar", origin=JarOrigin.HOMEMADE)
        session.commit()
        token = self._token(self._inspect(client, archive))

        response = client.post(
            "/backup/restore",
            data={"pending": token, "confirm": "replace"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert backup_service.current_counts(session)["jar"] == 1
        assert not backup_service.pending_path(token).exists()

    def test_the_result_says_where_the_old_notebook_went(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        token = self._token(self._inspect(client, archive))

        response = client.post(
            "/backup/restore", data={"pending": token, "confirm": "replace"}
        )

        assert "Restored." in response.text
        assert "backups/before-restore-" in response.text

    def test_the_token_alone_is_not_a_yes(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        token = self._token(self._inspect(client, archive))
        backup_service.wipe(session)
        session.commit()

        response = client.post("/backup/restore", data={"pending": token})

        assert response.status_code == 400
        assert backup_service.current_counts(session)["jar"] == 0

    def test_cancelling_throws_the_upload_away(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        token = self._token(self._inspect(client, archive))

        response = client.post(
            "/backup/restore/cancel", data={"pending": token}, follow_redirects=False
        )

        assert response.status_code == 303
        assert not backup_service.pending_path(token).exists()
        assert backup_service.current_counts(session)["jar"] == 1

    def test_a_token_cannot_be_used_twice(self, client, session):
        seed(session)
        archive = client.get("/backup/export").content
        token = self._token(self._inspect(client, archive))
        client.post("/backup/restore", data={"pending": token, "confirm": "replace"})

        response = client.post(
            "/backup/restore", data={"pending": token, "confirm": "replace"}
        )

        assert response.status_code == 400
        assert "expired" in response.text

    @pytest.mark.parametrize("token", ["../../zakvaska", "x" * 32, "", "ABCDEF" * 6])
    def test_a_token_is_never_a_path(self, client, token):
        response = client.post(
            "/backup/restore", data={"pending": token, "confirm": "replace"}
        )

        assert response.status_code == 400

    def test_a_bad_file_is_refused_at_the_first_step(self, client):
        pending = get_settings().data_dir / backup_service.PENDING_DIR
        shutil.rmtree(pending, ignore_errors=True)

        response = client.post(
            "/backup/inspect",
            files={"archive": ("notes.txt", b"not an export", "application/zip")},
        )

        assert response.status_code == 400
        assert "not a zip" in response.text
        assert list(pending.glob("*.zip")) == []

    def test_an_older_export_says_it_was_brought_forward(self, client, tmp_path):
        response = self._inspect(client, old_export(tmp_path).read_bytes())

        assert response.status_code == 200
        assert "older version" in response.text
