"""Picking jars to set against each other, and the page that draws them."""

from __future__ import annotations

from app.models.enums import JarOrigin
from app.models.jar import Jar
from app.services import compare
from app.services import jars as jar_service


def _jar(session, name, **fields) -> Jar:
    jar = Jar(name=name, origin=JarOrigin.HOMEMADE, **fields)
    session.add(jar)
    session.commit()
    return jar


class TestTheList:
    def test_it_keeps_the_order_jars_were_added_in(self, session):
        a, b, c = (_jar(session, n) for n in ("A", "B", "C"))
        for jar in (c, a, b):
            assert compare.add(session, jar)
        assert compare.chosen_ids(session) == [c.id, a.id, b.id]
        assert [j.name for j in compare.chosen_jars(session)] == ["C", "A", "B"]

    def test_adding_twice_adds_once(self, session):
        jar = _jar(session, "A")
        compare.add(session, jar)
        compare.add(session, jar)
        assert compare.chosen_ids(session) == [jar.id]

    def test_it_holds_only_so_many(self, session):
        jars = [_jar(session, f"J{n}") for n in range(compare.MOST + 1)]
        results = [compare.add(session, jar) for jar in jars]
        assert results == [True] * compare.MOST + [False]
        assert len(compare.chosen_ids(session)) == compare.MOST
        assert compare.is_full(session)

    def test_taking_one_out_and_clearing(self, session):
        a, b = _jar(session, "A"), _jar(session, "B")
        compare.add(session, a)
        compare.add(session, b)
        compare.remove(session, a.id)
        assert compare.chosen_ids(session) == [b.id]
        compare.clear(session)
        assert compare.chosen_ids(session) == []

    def test_an_archived_jar_leaves_the_picture_but_not_the_list(self, session):
        a, b = _jar(session, "A"), _jar(session, "B")
        compare.add(session, a)
        compare.add(session, b)
        jar_service.set_archived(session, a, True)
        assert [j.name for j in compare.chosen_jars(session)] == ["B"]
        jar_service.set_archived(session, a, False)
        assert [j.name for j in compare.chosen_jars(session)] == ["A", "B"]

    def test_rubbish_in_the_setting_is_ignored(self, session):
        from app.services import settings_store

        settings_store.set_setting(session, compare.KEY, "3,,x, 7 ,3,-1")
        assert compare.chosen_ids(session) == [3, 7]


class TestTheJarPage:
    def test_a_jar_offers_to_be_added_and_then_to_be_taken_out(self, client, session):
        jar_id = _jar(session, "Old Rye").id
        session.rollback()

        before = client.get(f"/jars/{jar_id}").text
        assert f'action="/compare/{jar_id}/add"' in before
        assert "Add to comparison" in before

        done = client.post(
            f"/compare/{jar_id}/add", data={"next": f"/jars/{jar_id}"},
            follow_redirects=False,
        )
        assert done.status_code == 303
        assert done.headers["location"] == f"/jars/{jar_id}"

        after = client.get(f"/jars/{jar_id}").text
        assert f'action="/compare/{jar_id}/remove"' in after
        assert "in the comparison" in after
        assert 'href="/compare"' in after

    def test_the_edit_page_has_it_too_and_comes_back_to_itself(self, client, session):
        jar_id = _jar(session, "Old Rye").id
        session.rollback()

        page = client.get(f"/jars/{jar_id}/edit").text
        assert f'action="/compare/{jar_id}/add"' in page
        assert f'name="next" value="/jars/{jar_id}/edit"' in page

    def test_a_new_jar_form_has_nothing_to_add(self, client):
        assert "/compare/" not in client.get("/jars/new").text

    def test_it_never_sends_you_off_the_site(self, client, session):
        jar_id = _jar(session, "Old Rye").id
        session.rollback()
        done = client.post(
            f"/compare/{jar_id}/add", data={"next": "//evil.example/x"},
            follow_redirects=False,
        )
        assert done.headers["location"] == f"/jars/{jar_id}"

    def test_a_jar_that_is_not_there_cannot_be_added(self, client):
        assert client.post("/compare/999/add").status_code == 404


class TestThePage:
    def test_empty_it_says_how_and_suggests_the_pair_on_one_flour(self, client, session):
        _jar(session, "Homemade", flour_type="whole rye")
        _jar(session, "Bought", flour_type="whole rye")
        _jar(session, "Wheat", flour_type="bread flour")
        session.rollback()

        page = client.get("/compare").text
        assert "Nothing picked yet" in page
        assert "Add to comparison" in page
        assert 'action="/compare/suggested"' in page
        assert "Homemade" in page and "Bought" in page

        client.post("/compare/suggested")
        page = client.get("/compare").text
        assert "Nothing picked yet" not in page
        assert page.count('class="chip compare-chip"') == 2

    def test_each_jar_can_be_taken_out_from_the_page(self, client, session):
        a, b = _jar(session, "A").id, _jar(session, "B").id
        session.rollback()
        client.post(f"/compare/{a}/add")
        client.post(f"/compare/{b}/add")

        page = client.get("/compare").text
        assert f'action="/compare/{a}/remove"' in page
        client.post(f"/compare/{a}/remove", data={"next": "/compare"})
        assert client.get("/compare").text.count('class="chip compare-chip"') == 1

    def test_it_belongs_to_the_jars_section(self, client):
        page = client.get("/compare").text
        nav = page.split('<nav class="sectionnav"')[1].split("</nav>")[0]
        here = nav.split("is-here")[1][:200]
        assert "<span>Jars</span>" in here or 'href="/"' in here
