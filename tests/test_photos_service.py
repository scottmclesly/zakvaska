"""Storing photos: orientation, thumbnails, EXIF timestamps, and the files."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image

from app.models.enums import PhotoOwner
from app.services import photos as photo_service


def make_image(
    size=(120, 60), colour=(200, 120, 60), fmt="JPEG", exif=None, mode="RGB"
) -> bytes:
    image = Image.new(mode, size, colour)
    buffer = BytesIO()
    if exif is not None:
        image.save(buffer, fmt, exif=exif)
    else:
        image.save(buffer, fmt)
    return buffer.getvalue()


def exif_with(**tags) -> bytes:
    exif = Image.Exif()
    for tag, value in tags.items():
        exif[int(tag)] = value
    return exif.tobytes()


def opened(relative: str) -> Image.Image:
    return Image.open(photo_service.absolute(relative))


class TestStoring:
    def test_it_writes_a_full_image_and_a_thumbnail(self, frozen_now):
        stored = photo_service.store_bytes(make_image(), now=frozen_now)

        assert photo_service.absolute(stored.path).is_file()
        assert photo_service.absolute(stored.thumb_path).is_file()
        assert stored.path != stored.thumb_path

    def test_files_land_under_year_and_month(self, frozen_now):
        """docs/TODO-v1.md: data/photos/YYYY/MM/."""
        stored = photo_service.store_bytes(make_image(), now=frozen_now)
        # frozen_now is 2026-03-15 12:00 UTC, which is 08:00 in New York.
        assert stored.path.startswith("2026/03/")
        assert stored.thumb_path.startswith("2026/03/")

    def test_everything_is_stored_as_jpeg(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(fmt="PNG"), now=frozen_now
        )
        assert opened(stored.path).format == "JPEG"

    def test_a_transparent_png_does_not_blow_up(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(fmt="PNG", mode="RGBA", colour=(10, 20, 30, 128)),
            now=frozen_now,
        )
        assert opened(stored.path).mode == "RGB"

    def test_the_thumbnail_is_small(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(size=(1600, 1200)), now=frozen_now
        )
        thumb = opened(stored.thumb_path)
        assert max(thumb.size) <= photo_service.THUMB_EDGE

    def test_an_enormous_photo_is_scaled_down(self, frozen_now):
        """A phone photo should not land on a Pi's SD card at full size."""
        stored = photo_service.store_bytes(
            make_image(size=(4000, 3000)), now=frozen_now
        )
        full = opened(stored.path)
        assert max(full.size) == photo_service.MAX_EDGE
        # Still the same shape.
        assert full.size[0] / full.size[1] == pytest.approx(4 / 3, abs=0.01)

    def test_a_small_photo_is_left_alone(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(size=(120, 60)), now=frozen_now
        )
        assert opened(stored.path).size == (120, 60)

    def test_two_photos_never_collide(self, frozen_now):
        first = photo_service.store_bytes(make_image(), now=frozen_now)
        second = photo_service.store_bytes(make_image(), now=frozen_now)
        assert first.path != second.path


class TestOrientation:
    """The acceptance check: a photo shot on a phone displays the right way up."""

    def test_a_rotated_photo_comes_out_upright(self, frozen_now):
        # Orientation 6 means "rotate 90° clockwise to display".
        landscape = make_image(size=(120, 60), exif=exif_with(**{"274": 6}))
        stored = photo_service.store_bytes(landscape, now=frozen_now)

        # The pixels themselves are rotated, so width and height swap.
        assert opened(stored.path).size == (60, 120)

    def test_the_thumbnail_is_rotated_too(self, frozen_now):
        landscape = make_image(size=(120, 60), exif=exif_with(**{"274": 6}))
        stored = photo_service.store_bytes(landscape, now=frozen_now)
        thumb = opened(stored.thumb_path)
        assert thumb.size[1] > thumb.size[0]

    def test_an_unrotated_photo_is_untouched(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(size=(120, 60), exif=exif_with(**{"274": 1})),
            now=frozen_now,
        )
        assert opened(stored.path).size == (120, 60)

    def test_the_orientation_tag_is_not_left_behind(self, frozen_now):
        """Rotating the pixels and keeping the tag would rotate it twice."""
        stored = photo_service.store_bytes(
            make_image(size=(120, 60), exif=exif_with(**{"274": 6})),
            now=frozen_now,
        )
        assert not opened(stored.path).getexif().get(274)


class TestTakenAt:
    def test_it_reads_the_cameras_timestamp(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(exif=exif_with(**{"36867": "2026:03:15 09:30:00"})),
            now=frozen_now,
        )
        # Written as local wall-clock in New York, stored as UTC.
        assert stored.taken_at == datetime(2026, 3, 15, 13, 30, tzinfo=UTC)

    def test_without_exif_it_falls_back_to_now(self, frozen_now):
        stored = photo_service.store_bytes(make_image(), now=frozen_now)
        assert stored.taken_at == frozen_now

    def test_a_nonsense_timestamp_falls_back_rather_than_failing(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(exif=exif_with(**{"36867": "not a date"})),
            now=frozen_now,
        )
        assert stored.taken_at == frozen_now

    def test_the_folder_follows_the_photo_not_the_upload(self, frozen_now):
        """A photo taken in January filed in March would be hard to find."""
        stored = photo_service.store_bytes(
            make_image(exif=exif_with(**{"36867": "2026:01:04 09:30:00"})),
            now=frozen_now,
        )
        assert stored.path.startswith("2026/01/")

    def test_gps_and_the_rest_of_the_exif_are_dropped(self, frozen_now):
        stored = photo_service.store_bytes(
            make_image(exif=exif_with(**{"36867": "2026:03:15 09:30:00"})),
            now=frozen_now,
        )
        assert dict(opened(stored.path).getexif()) == {}


class TestRefusals:
    def test_an_empty_file(self):
        with pytest.raises(photo_service.PhotoError, match="empty"):
            photo_service.store_bytes(b"")

    def test_something_that_is_not_an_image(self):
        with pytest.raises(photo_service.PhotoError, match="not an image"):
            photo_service.store_bytes(b"this is a text file, not a photo")

    def test_a_file_that_is_too_big(self):
        with pytest.raises(photo_service.PhotoError, match="larger than"):
            photo_service.store_bytes(b"x" * (photo_service.MAX_UPLOAD_BYTES + 1))

    def test_a_path_outside_the_photo_directory(self):
        with pytest.raises(photo_service.PhotoError):
            photo_service.absolute("../zakvaska.db")


class TestAttaching:
    def test_attaching_to_a_jar(self, session, frozen_now):
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=1,
            data=make_image(), caption="the lid", now=frozen_now,
        )
        session.commit()

        assert photo.id is not None
        assert photo.caption == "the lid"
        assert photo.url == f"/photos/{photo.id}/file"
        assert photo.thumb_url == f"/photos/{photo.id}/thumb"

    def test_listing_is_oldest_first(self, session, frozen_now):
        from datetime import timedelta

        later = photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=7,
            data=make_image(), now=frozen_now + timedelta(hours=1),
        )
        earlier = photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=7,
            data=make_image(), now=frozen_now,
        )
        session.commit()

        found = photo_service.list_for(session, PhotoOwner.BAKE, 7)
        assert [p.id for p in found] == [earlier.id, later.id]

    def test_owners_do_not_see_each_others_photos(self, session, frozen_now):
        photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=1,
            data=make_image(), now=frozen_now,
        )
        photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=1,
            data=make_image(), now=frozen_now,
        )
        session.commit()

        assert len(photo_service.list_for(session, PhotoOwner.JAR, 1)) == 1
        assert len(photo_service.list_for(session, PhotoOwner.BAKE, 1)) == 1
        assert photo_service.list_for(session, PhotoOwner.JAR, 2) == []

    def test_photos_by_owner_groups_in_one_go(self, session, frozen_now):
        for owner_id in (1, 1, 2):
            photo_service.attach(
                session, owner_type=PhotoOwner.FEEDING, owner_id=owner_id,
                data=make_image(), now=frozen_now,
            )
        session.commit()

        grouped = photo_service.photos_by_owner(
            session, PhotoOwner.FEEDING, [1, 2, 3]
        )
        assert len(grouped[1]) == 2
        assert len(grouped[2]) == 1
        assert 3 not in grouped

    def test_photos_by_owner_with_nothing_asked_for(self, session):
        assert photo_service.photos_by_owner(session, PhotoOwner.JAR, []) == {}

    def test_counts(self, session, frozen_now):
        for _ in range(3):
            photo_service.attach(
                session, owner_type=PhotoOwner.JAR, owner_id=4,
                data=make_image(), now=frozen_now,
            )
        session.commit()
        assert photo_service.counts_for(session, PhotoOwner.JAR, [4, 5]) == {4: 3}


class TestChangingAndRemoving:
    def test_setting_a_caption(self, session, frozen_now):
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=1,
            data=make_image(), now=frozen_now,
        )
        photo_service.set_caption(session, photo, "day three")
        session.commit()
        assert photo.caption == "day three"

    def test_deleting_takes_the_files_with_it(self, session, frozen_now):
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=1,
            data=make_image(), now=frozen_now,
        )
        session.commit()
        full = photo_service.absolute(photo.path)
        thumb = photo_service.absolute(photo.thumb_path)
        assert full.is_file() and thumb.is_file()

        photo_service.delete_photo(session, photo)
        session.commit()

        assert not full.exists()
        assert not thumb.exists()
        assert photo_service.list_for(session, PhotoOwner.JAR, 1) == []

    def test_deleting_survives_a_file_that_is_already_gone(
        self, session, frozen_now
    ):
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=1,
            data=make_image(), now=frozen_now,
        )
        session.commit()
        photo_service.absolute(photo.path).unlink()

        photo_service.delete_photo(session, photo)
        session.commit()
        assert photo_service.list_for(session, PhotoOwner.JAR, 1) == []
