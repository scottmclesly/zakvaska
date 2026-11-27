"""Photos through HTTP, the way a phone uses them.

The last class is Phase 5's acceptance check from docs/dev/TODO-v1.md: a photo
shot on a phone uploads, displays correctly rotated, and survives restart.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.models.enums import PhotoOwner
from app.services import photos as photo_service
from tests.test_bake_routes import seed_recipe, start
from tests.test_photos_service import exif_with, make_image

JAR_FIELDS = {
    "origin": "homemade",
    "state": "active",
    "feed_interval_room_h": "12",
    "feed_interval_fridge_h": "168",
}


def create_jar(client, name="Homemade rye") -> int:
    response = client.post(
        "/jars/new", data={"name": name, **JAR_FIELDS}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return int(re.fullmatch(r"/jars/(\d+)", response.headers["location"]).group(1))


def upload(client, owner_type, owner_id, *, data=None, caption="", filename="crumb.jpg"):
    return client.post(
        "/photos/upload",
        data={"owner_type": owner_type, "owner_id": owner_id, "caption": caption},
        files={"photo": (filename, data or make_image(), "image/jpeg")},
        follow_redirects=False,
    )


def only_photo(session, owner_type, owner_id):
    found = photo_service.list_for(session, owner_type, owner_id)
    assert len(found) == 1, found
    return found[0]


class TestUploading:
    def test_a_photo_of_a_jar_lands_on_the_jar_page(self, client, session):
        jar_id = create_jar(client)

        response = upload(client, "jar", jar_id, caption="day three")

        assert response.status_code == 303
        assert response.headers["location"] == f"/jars/{jar_id}"
        photo = only_photo(session, PhotoOwner.JAR, jar_id)
        assert photo.caption == "day three"
        assert photo.thumb_url in client.get(f"/jars/{jar_id}").text

    def test_a_photo_of_a_bake_lands_on_the_bake_page(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)

        response = upload(client, "bake", bake_id)

        assert response.headers["location"] == f"/bakes/{bake_id}"
        photo = only_photo(session, PhotoOwner.BAKE, bake_id)
        assert photo.thumb_url in client.get(f"/bakes/{bake_id}").text

    def test_a_caption_is_optional(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id, caption="   ")
        assert only_photo(session, PhotoOwner.JAR, jar_id).caption is None

    def test_an_empty_file_field_is_not_an_error(self, client, session):
        """The field is shared with forms where a photo is optional."""
        jar_id = create_jar(client)

        response = client.post(
            "/photos/upload",
            data={"owner_type": "jar", "owner_id": jar_id},
            files={"photo": ("", b"", "application/octet-stream")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert photo_service.list_for(session, PhotoOwner.JAR, jar_id) == []

    def test_something_that_is_not_an_image_is_refused(self, client):
        jar_id = create_jar(client)

        response = upload(client, "jar", jar_id, data=b"not a photo at all")

        assert response.status_code == 400
        assert "not an image" in response.text

    def test_an_unknown_owner_type(self, client):
        response = upload(client, "pantry", 1)
        assert response.status_code == 400

    def test_an_owner_that_does_not_exist(self, client):
        response = upload(client, "jar", 999)
        assert response.status_code == 404


class TestServing:
    def test_the_full_image_and_the_thumbnail(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id, data=make_image(size=(1200, 900)))
        photo = only_photo(session, PhotoOwner.JAR, jar_id)

        full = client.get(photo.url)
        thumb = client.get(photo.thumb_url)

        assert full.status_code == 200
        assert full.headers["content-type"] == "image/jpeg"
        assert thumb.status_code == 200
        assert len(thumb.content) < len(full.content)

    def test_photos_are_cached_hard(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)
        photo = only_photo(session, PhotoOwner.JAR, jar_id)

        assert "immutable" in client.get(photo.url).headers["cache-control"]

    def test_a_missing_thumbnail_falls_back_to_the_full_image(
        self, client, session
    ):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)
        photo = only_photo(session, PhotoOwner.JAR, jar_id)
        photo_service.absolute(photo.thumb_path).unlink()

        response = client.get(photo.thumb_url)

        assert response.status_code == 200
        assert response.content == photo_service.absolute(photo.path).read_bytes()

    def test_a_missing_file_is_a_404_not_a_crash(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)
        photo = only_photo(session, PhotoOwner.JAR, jar_id)
        photo_service.absolute(photo.path).unlink()
        photo_service.absolute(photo.thumb_path).unlink()

        assert client.get(photo.url).status_code == 404
        assert client.get(photo.thumb_url).status_code == 404

    def test_an_unknown_photo_is_a_404(self, client):
        assert client.get("/photos/404/file").status_code == 404
        assert client.get("/photos/404/thumb").status_code == 404


class TestCaptionAndDelete:
    def test_captioning_from_the_gallery(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)
        photo = only_photo(session, PhotoOwner.JAR, jar_id)

        response = client.post(
            f"/photos/{photo.id}/caption",
            data={"caption": "doubled in 5 h"},
            follow_redirects=False,
        )

        assert response.headers["location"] == f"/jars/{jar_id}"
        assert "doubled in 5 h" in client.get(f"/jars/{jar_id}").text

    def test_clearing_a_caption(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id, caption="wrong")
        photo = only_photo(session, PhotoOwner.JAR, jar_id)

        client.post(f"/photos/{photo.id}/caption", data={"caption": ""})

        session.expire_all()
        assert only_photo(session, PhotoOwner.JAR, jar_id).caption is None

    def test_deleting_a_misfired_upload(self, client, session):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)
        photo = only_photo(session, PhotoOwner.JAR, jar_id)
        path = photo_service.absolute(photo.path)

        response = client.post(f"/photos/{photo.id}/delete", follow_redirects=False)

        assert response.headers["location"] == f"/jars/{jar_id}"
        assert not path.exists()
        assert photo_service.list_for(session, PhotoOwner.JAR, jar_id) == []

    def test_deleting_a_bake_photo_returns_to_the_bake(self, client, session):
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        upload(client, "bake", bake_id)
        photo = only_photo(session, PhotoOwner.BAKE, bake_id)

        response = client.post(f"/photos/{photo.id}/delete", follow_redirects=False)

        assert response.headers["location"] == f"/bakes/{bake_id}"


class TestOnTheTimeline:
    def test_a_photo_taken_while_feeding(self, client, session):
        jar_id = create_jar(client)

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40"},
            files={"photo": ("jar.jpg", make_image(), "image/jpeg")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        from sqlalchemy import select

        from app.models.feeding import Feeding

        feeding = session.scalars(select(Feeding)).one()
        photo = only_photo(session, PhotoOwner.FEEDING, feeding.id)
        # It shows on the jar's timeline, not on a page of its own.
        assert photo.thumb_url in client.get(f"/jars/{jar_id}").text

    def test_a_photo_taken_while_observing(self, client, session):
        jar_id = create_jar(client)

        client.post(
            f"/jars/{jar_id}/observe",
            data={"start_height_mm": "40", "height_mm": "80"},
            files={"photo": ("jar.jpg", make_image(), "image/jpeg")},
            follow_redirects=False,
        )

        from sqlalchemy import select

        from app.models.observation import Observation

        observation = session.scalars(select(Observation)).one()
        photo = only_photo(session, PhotoOwner.OBSERVATION, observation.id)
        assert photo.thumb_url in client.get(f"/jars/{jar_id}").text

    def test_feeding_without_a_photo_still_works(self, client, session):
        jar_id = create_jar(client)

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "100% hydration" in client.get(f"/jars/{jar_id}").text

    def test_an_unreadable_photo_does_not_lose_the_feeding(self, client, session):
        """Losing the numbers because the camera file was odd would be worse."""
        jar_id = create_jar(client)

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40"},
            files={"photo": ("jar.jpg", b"not an image", "image/jpeg")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "100% hydration" in client.get(f"/jars/{jar_id}").text


class TestComparing:
    def test_with_nothing_to_compare(self, client):
        page = client.get("/photos/compare")

        assert page.status_code == 200
        assert "Not enough bake photos yet" in page.text

    def test_with_only_one_photo(self, client, session):
        recipe = seed_recipe(session)
        upload(client, "bake", start(client, recipe))

        page = client.get("/photos/compare")

        assert "There is one so far." in page.text

    def test_two_loaves_side_by_side(self, client, session):
        recipe = seed_recipe(session)
        first = start(client, recipe)
        second = start(client, recipe, total_flour_g="600")
        upload(client, "bake", first, caption="open crumb")
        upload(client, "bake", second, caption="tight crumb")
        left, right = photo_service.bake_photos(session)

        page = client.get(f"/photos/compare?a={right.id}&b={left.id}")

        assert page.status_code == 200
        assert page.text.count('class="compare-side"') == 2
        assert "open crumb" in page.text
        assert "tight crumb" in page.text
        assert f"/bakes/{first}" in page.text
        assert f"/bakes/{second}" in page.text

    def test_one_side_picked_asks_for_the_other(self, client, session):
        recipe = seed_recipe(session)
        upload(client, "bake", start(client, recipe))
        upload(client, "bake", start(client, recipe))
        chosen = photo_service.bake_photos(session)[0]

        page = client.get(f"/photos/compare?a={chosen.id}")

        assert "Pick a photo for this side." in page.text

    def test_a_finished_loaf_offers_to_be_set_beside_the_last_one(self, client, session):
        """The way in is the loaf itself, not a button in the header: its
        framed photo on the left, and the menu open on the previous bake of
        the same recipe."""
        recipe = seed_recipe(session)
        first, second = start(client, recipe), start(client, recipe)
        upload(client, "bake", first, caption="last time")
        upload(client, "bake", second, caption="this time")
        client.post(f"/bakes/{second}/finish", data={"status": "done"})

        page = client.get(f"/bakes/{second}").text
        form = page.split('class="compare-with"')[1].split("</form>")[0]
        mine = re.search(r'name="a" value="(\d+)"', form).group(1)
        chosen = re.search(r'<option value="(\d+)" selected>([^<]*)', form)

        assert 'action="/photos/compare"' in page
        # Under what went into the loaf, not up beside the photograph.
        assert page.index("showcase-record") < page.index('class="compare-with"')
        assert "The same recipe" in form
        assert "last time" in chosen.group(2)
        assert chosen.group(1) != mine

        both = client.get(f"/photos/compare?a={mine}&b={chosen.group(1)}").text
        assert "this time" in both and "last time" in both

    def test_a_loaf_with_nothing_to_be_compared_with_does_not_offer(self, client, session):
        recipe = seed_recipe(session)
        only = start(client, recipe)
        upload(client, "bake", only)
        client.post(f"/bakes/{only}/finish", data={"status": "done"})

        assert 'class="compare-with"' not in client.get(f"/bakes/{only}").text

    def test_a_loaf_s_photo_can_be_carried_into_the_comparison(self, client, session):
        """From the large preview: this exact photo, on the left."""
        recipe = seed_recipe(session)
        bake_id = start(client, recipe)
        upload(client, "bake", bake_id)

        page = client.get(f"/bakes/{bake_id}").text

        assert re.search(r'href="/photos/compare\?a=\d+">Compare<', page)

    def test_a_jar_s_photo_has_no_such_link(self, client):
        jar_id = create_jar(client)
        upload(client, "jar", jar_id)

        assert "/photos/compare" not in client.get(f"/jars/{jar_id}").text

    def test_there_is_no_button_for_it_in_the_header(self, client, session):
        bake_id = start(client, seed_recipe(session))
        for path in ("/bakes", f"/bakes/{bake_id}"):
            actions = client.get(path).text.split('<nav class="topnav"')[1].split("</nav>")[0]
            assert "/photos/compare" not in actions, path

    def test_jar_photos_are_not_offered(self, client, session):
        recipe = seed_recipe(session)
        upload(client, "bake", start(client, recipe))
        upload(client, "bake", start(client, recipe))
        jar_id = create_jar(client)
        upload(client, "jar", jar_id, caption="just the lid")

        page = client.get("/photos/compare")

        assert "just the lid" not in page.text


class TestPhaseFiveAcceptance:
    """A photo shot on a phone uploads, displays rotated, survives restart."""

    def test_the_whole_round_trip(self, client, session, data_dir):
        jar_id = create_jar(client)
        # What a phone actually sends: a landscape sensor frame plus an
        # orientation tag saying to turn it a quarter turn.
        from_phone = make_image(size=(1200, 900), exif=exif_with(**{"274": 6}))

        assert upload(
            client, "jar", jar_id, data=from_phone, caption="day three"
        ).status_code == 303

        photo = only_photo(session, PhotoOwner.JAR, jar_id)
        served = client.get(photo.url)
        assert served.status_code == 200

        from io import BytesIO

        shown = Image.open(BytesIO(served.content))
        # Portrait now, with nothing left for the browser to rotate.
        assert shown.height > shown.width
        assert not shown.getexif().get(274)

        # The file is on disk under data/photos/YYYY/MM, not in the database.
        on_disk = data_dir / "photos" / photo.path
        assert on_disk.is_file()
        assert re.fullmatch(r"\d{4}/\d{2}/[0-9a-f]{16}\.jpg", photo.path)

        # Restart: a new app instance, same data dir.
        with TestClient(app) as restarted:
            again = restarted.get(photo.url)
            assert again.status_code == 200
            assert again.content == served.content
            assert "day three" in restarted.get(f"/jars/{jar_id}").text
