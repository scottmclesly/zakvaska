"""A finished bake's page: the loaf shown off, with nothing lost.

While a bake is underway its page is for doing it. Once it is done the same
address becomes the loaf's own page — photograph, verdict, figures — with the
day and the running sheet kept below as the record. These check that the
switch happens on the bake's status and that every figure survives it.
"""

from __future__ import annotations

from app.models.enums import PhotoOwner
from app.services import photos as photo_service
from tests.test_bake_routes import seed_recipe, start
from tests.test_photos_service import make_image


def _finish(client, bake_id, status="done"):
    answer = client.post(
        f"/bakes/{bake_id}/finish", data={"status": status}, follow_redirects=False
    )
    assert answer.status_code == 303


def _result(client, bake_id, **fields):
    data = {"rating": "4", "crust": "thick", "crumb": "open", "taste": "sour",
            "rise": "good", "next_time": "Proof longer."}
    data.update(fields)
    answer = client.post(f"/bakes/{bake_id}/result", data=data, follow_redirects=False)
    assert answer.status_code == 303, answer.text


class TestWhichPageItIs:
    def test_a_bake_underway_keeps_the_page_for_doing_it(self, client, session):
        bake_id = start(client, seed_recipe(session))

        page = client.get(f"/bakes/{bake_id}").text

        assert 'class="showcase"' not in page
        assert 'id="bake-live"' in page
        assert "Running sheet" in page

    def test_a_finished_bake_gets_the_loaf_s_own_page(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id)

        page = client.get(f"/bakes/{bake_id}").text

        assert 'class="showcase"' in page
        # Nothing left to steer, so nothing refreshing itself.
        assert 'id="bake-live"' not in page

    def test_a_failed_bake_is_finished_too(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id, status="failed")

        assert 'class="showcase"' in client.get(f"/bakes/{bake_id}").text

    def test_reopening_it_brings_the_working_page_back(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id)
        _finish(client, bake_id, status="in_progress")

        assert 'class="showcase"' not in client.get(f"/bakes/{bake_id}").text


class TestNothingIsLost:
    def test_every_figure_and_every_section_is_still_there(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id)
        _result(client, bake_id)

        page = client.get(f"/bakes/{bake_id}").text

        # The figures.
        for label in ("Started", "Took", "Stages", "Flour"):
            assert f">{label}</dt>" in page, label
        # The verdict, in full.
        for word in ("thick", "open", "sour", "good", "Proof longer."):
            assert word in page, word
        assert "4 out of 5" in page
        # What went into it, and how the day went, step by step.
        assert "What went into it" in page
        assert "Total dough" in page
        assert "How the day went" in page
        assert "Step by step" in page
        assert page.count('class="card stage-step') >= 1
        # And the things you can still do.
        assert f'href="/bakes/{bake_id}/result"' in page
        assert "Edit the result" in page
        assert f'action="/bakes/{bake_id}/finish"' in page
        assert f'action="/bakes/{bake_id}/archive"' in page
        assert 'action="/photos/upload"' in page

    def test_one_with_nothing_written_up_asks_for_it(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id)

        page = client.get(f"/bakes/{bake_id}").text

        assert "Record the result" in page
        assert "Edit the result" not in page


class TestThePhotograph:
    def test_the_first_photo_leads_the_page_and_opens_large(self, client, session):
        bake_id = start(client, seed_recipe(session))
        photo = photo_service.attach(
            session, owner_type=PhotoOwner.BAKE, owner_id=bake_id,
            data=make_image(), caption="crumb shot",
        )
        session.commit()
        _finish(client, bake_id)

        page = client.get(f"/bakes/{bake_id}").text
        cover = page.split('class="showcase-cover"')[1].split("</div>")[0]

        assert f'data-photo-open="photo-{photo.id}"' in cover
        assert "crumb shot" in cover
        # The gallery below still has it, with its preview to open.
        assert f'<dialog class="photo-view" id="photo-{photo.id}"' in page

    def test_without_a_photo_the_drawing_stands_in_and_says_so(self, client, session):
        bake_id = start(client, seed_recipe(session))
        _finish(client, bake_id)

        page = client.get(f"/bakes/{bake_id}").text

        assert 'class="showcase-standin"' in page
        assert "No photo of this one yet" in page
        assert "loaf-art" in page.split('class="showcase-standin"')[1][:600]
