"""HEIC uploads: the iPhone's format, and keeping the original.

The fixture is generated here with pillow-heif rather than committed as a
binary, so the test proves the installed libheif can both write and read
what the app will be handed.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image

from app.models.enums import JarOrigin, PhotoOwner
from app.services import backup as backup_service
from app.services import jars as jar_service
from app.services import photos as photo_service
from tests.test_photos_service import exif_with, make_image, opened


def make_heic(size=(120, 60), colour=(200, 120, 60), exif=None) -> bytes:
    """A real HEIC file, encoded by the same library that will decode it."""
    image = Image.new("RGB", size, colour)
    buffer = BytesIO()
    if exif is not None:
        image.save(buffer, "HEIF", exif=exif, quality=60)
    else:
        image.save(buffer, "HEIF", quality=60)
    return buffer.getvalue()


def a_jar(session):
    jar = jar_service.create_jar(
        session, name="Homemade rye", origin=JarOrigin.HOMEMADE, flour_type="whole rye"
    )
    session.commit()
    return jar


class TestTheLibrary:
    def test_pillow_reads_heic_at_all(self):
        """If this fails, nothing else in this file means anything."""
        image = Image.open(BytesIO(make_heic()))
        image.load()
        assert image.format == "HEIF"

    def test_the_opener_is_registered_by_importing_the_service(self):
        """Not in the app's lifespan: a test never starts the app."""
        assert "HEIF" in photo_service.ALLOWED_FORMATS


class TestUploading:
    def test_a_heic_is_accepted(self, frozen_now):
        stored = photo_service.store_bytes(make_heic(), now=frozen_now)
        assert photo_service.absolute(stored.path).is_file()

    def test_pages_are_served_a_jpeg(self, frozen_now):
        """Only Safari renders HEIC, so the rendition is not optional."""
        stored = photo_service.store_bytes(make_heic(), now=frozen_now)
        assert opened(stored.path).format == "JPEG"
        assert opened(stored.thumb_path).format == "JPEG"

    def test_the_original_is_kept_as_heic(self, frozen_now):
        stored = photo_service.store_bytes(make_heic(), now=frozen_now)
        assert stored.original_path.endswith(".heic")
        assert opened(stored.original_path).format == "HEIF"

    def test_the_original_is_byte_for_byte_what_arrived(self, frozen_now):
        data = make_heic()
        stored = photo_service.store_bytes(data, now=frozen_now)
        assert photo_service.absolute(stored.original_path).read_bytes() == data

    def test_a_jpeg_upload_keeps_its_original_too(self, frozen_now):
        data = make_image()
        stored = photo_service.store_bytes(data, now=frozen_now)
        assert stored.original_path.endswith(".jpg")
        assert photo_service.absolute(stored.original_path).read_bytes() == data

    def test_the_original_sits_beside_the_rendition(self, frozen_now):
        stored = photo_service.store_bytes(make_heic(), now=frozen_now)
        assert stored.original_path.startswith("2026/03/")
        assert stored.original_path != stored.path


class TestOrientation:
    """HEIF carries rotation in the container, not only in EXIF.

    libheif applies it while decoding and reports orientation 1, so a HEIC
    reaches the service already upright and exif_transpose has nothing left
    to do. That is worth pinning down: the thing that must not happen is the
    app rotating a second time. A synthesized HEIC cannot carry a live
    orientation tag at all — pillow-heif normalises it on the way in — so
    the EXIF-tag path is tested below with a JPEG, where it can be built.
    """

    def test_a_sideways_heic_comes_out_upright(self, frozen_now):
        upright = Image.new("RGB", (60, 120), (200, 120, 60))
        sensor = upright.rotate(90, expand=True)  # 120x60, lying on its side
        buffer = BytesIO()
        sensor.save(buffer, "HEIF", exif=exif_with(**{"274": 6}), quality=60)

        stored = photo_service.store_bytes(buffer.getvalue(), now=frozen_now)

        shown = opened(stored.path)
        assert shown.height > shown.width, "the rendition should be portrait"
        assert shown.getexif().get(274) in (None, 0, 1), "no orientation tag left"

    def test_an_oriented_jpeg_keeps_its_tag_in_the_original(self, frozen_now):
        """Untouched means untouched: the rendition is rotated, not the file."""
        sensor = Image.new("RGB", (120, 60), (200, 120, 60))
        buffer = BytesIO()
        sensor.save(buffer, "JPEG", exif=exif_with(**{"274": 6}))

        stored = photo_service.store_bytes(buffer.getvalue(), now=frozen_now)

        assert opened(stored.original_path).getexif().get(274) == 6
        shown = opened(stored.path)
        assert shown.height > shown.width
        assert shown.getexif().get(274) in (None, 0, 1)


class TestTakenAt:
    def test_the_heic_capture_time_is_read(self, frozen_now):
        data = make_heic(exif=exif_with(**{"36867": "2026:02:14 07:30:00"}))
        stored = photo_service.store_bytes(data, now=frozen_now)
        # 07:30 in New York is 12:30 UTC.
        assert stored.taken_at == datetime(2026, 2, 14, 12, 30, tzinfo=UTC)

    def test_a_heic_without_a_timestamp_falls_back_to_now(self, frozen_now):
        stored = photo_service.store_bytes(make_heic(), now=frozen_now)
        assert stored.taken_at == frozen_now


class TestTheSizeLimit:
    def test_the_cap_is_twenty_five_megabytes(self):
        assert photo_service.MAX_UPLOAD_BYTES == 25 * 1024 * 1024

    def test_something_larger_is_refused(self, frozen_now):
        too_big = b"\x00" * (photo_service.MAX_UPLOAD_BYTES + 1)
        with pytest.raises(photo_service.PhotoError, match="25 MB"):
            photo_service.store_bytes(too_big, now=frozen_now)


class TestThroughTheApp:
    def test_a_heic_can_be_uploaded_and_is_served_as_jpeg(self, client, session):
        jar = a_jar(session)
        response = client.post(
            "/photos/upload",
            data={"owner_type": "jar", "owner_id": jar.id},
            files={"photo": ("IMG_4021.HEIC", make_heic(), "image/heic")},
        )
        assert response.status_code == 200

        photo = photo_service.list_for(session, PhotoOwner.JAR, jar.id)[0]
        served = client.get(photo.url)
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/jpeg"

    def test_the_original_downloads_as_heic(self, client, session):
        jar = a_jar(session)
        data = make_heic()
        client.post(
            "/photos/upload",
            data={"owner_type": "jar", "owner_id": jar.id},
            files={"photo": ("IMG_4021.HEIC", data, "image/heic")},
        )
        photo = photo_service.list_for(session, PhotoOwner.JAR, jar.id)[0]

        got = client.get(photo.original_url)
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/heic"
        assert got.content == data

    def test_the_gallery_offers_the_original(self, client, session):
        jar = a_jar(session)
        client.post(
            "/photos/upload",
            data={"owner_type": "jar", "owner_id": jar.id},
            files={"photo": ("IMG_4021.HEIC", make_heic(), "image/heic")},
        )
        photo = photo_service.list_for(session, PhotoOwner.JAR, jar.id)[0]
        page = client.get(f"/jars/{jar.id}").text
        assert f"/photos/{photo.id}/original" in page

    def test_the_file_input_accepts_heic(self, client, session):
        jar = a_jar(session)
        assert 'accept="image/*,.heic,.heif"' in client.get(f"/jars/{jar.id}").text

    def test_a_photo_without_an_original_says_so(self, client, session):
        """Rows from before this change are still perfectly good photos."""
        jar = a_jar(session)
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=jar.id, data=make_image()
        )
        photo.original_path = None
        session.commit()

        assert client.get(f"/photos/{photo.id}/original").status_code == 404
        assert client.get(photo.url).status_code == 200


class TestDeleting:
    def test_deleting_takes_the_original_with_it(self, session, frozen_now):
        jar = a_jar(session)
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=jar.id,
            data=make_heic(), now=frozen_now,
        )
        session.commit()
        original = photo_service.absolute(photo.original_path)
        assert original.is_file()

        photo_service.delete_photo(session, photo)
        session.commit()
        assert not original.exists()


class TestBackup:
    def test_an_export_carries_the_originals(self, session, tmp_path, frozen_now):
        jar = a_jar(session)
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=jar.id,
            data=make_heic(), now=frozen_now,
        )
        session.commit()

        path = tmp_path / "export.zip"
        backup_service.write_export(path, session)
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        assert f"photos/{photo.original_path}" in names

    def test_a_restore_brings_the_original_back_unchanged(
        self, session, tmp_path, frozen_now
    ):
        jar = a_jar(session)
        data = make_heic()
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=jar.id,
            data=data, now=frozen_now,
        )
        session.commit()
        relative = photo.original_path

        path = tmp_path / "export.zip"
        backup_service.write_export(path, session)
        backup_service.wipe(session)
        session.commit()

        report = backup_service.restore(session, path)
        session.commit()

        assert report.photos >= 3, "original, rendition and thumbnail"
        assert photo_service.absolute(relative).read_bytes() == data
        restored = session.get(type(photo), photo.id)
        assert restored.original_path == relative
