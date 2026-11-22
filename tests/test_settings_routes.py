"""The settings page: display units, the feeding rhythm, busy blocks."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.busy_block import EVERY_DAY, WEEKDAYS, BusyBlock
from app.models.enums import BusyKind, JarOrigin
from app.models.jar import Jar
from app.services import busy as busy_service
from app.services import settings_store


def _jar(session, **fields) -> Jar:
    jar = Jar(name="Old Rye", origin=JarOrigin.HOMEMADE, **fields)
    session.add(jar)
    session.commit()
    return jar


# --- The page -----------------------------------------------------------


def test_the_settings_page_opens(client):
    page = client.get("/settings")

    assert page.status_code == 200
    assert "Feeding rhythm" in page.text
    assert "When you are busy" in page.text


def test_the_page_is_reachable_from_every_other_one(client):
    # It is in the footer, which base.html puts on every page.
    assert 'href="/settings"' in client.get("/").text


def test_an_empty_busy_list_says_so_and_opens_the_form(client):
    page = client.get("/settings")

    assert "Nothing here yet" in page.text
    # The example in the placeholder, as the plan asks: seed nothing, suggest.
    assert "Sleep 02:00" in page.text


# --- The feeding rhythm -------------------------------------------------


def test_the_rhythm_round_trips(client, session):
    response = client.post(
        "/settings/timing",
        data={"feeds_per_day": "1", "ribbon_span_h": "72", "ferment_temp": "75"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert settings_store.feeds_per_day(session) == 1
    assert settings_store.ribbon_span_h(session) == 72
    # Typed in °F (the default display unit), stored in Celsius.
    assert settings_store.default_ferment_temp_c(session) == pytest.approx(23.9, abs=0.1)


def test_the_defaults_are_the_ones_the_plan_asks_for(session):
    assert settings_store.feeds_per_day(session) == 2
    assert settings_store.ribbon_span_h(session) == 48
    # 80 °F, his proofing box.
    assert settings_store.default_ferment_temp_c(session) == pytest.approx(26.7, abs=0.1)


def test_a_rhythm_nobody_feeds_at_is_refused(client, session):
    response = client.post(
        "/settings/timing", data={"feeds_per_day": "9"}, follow_redirects=False
    )

    assert response.status_code == 400
    assert "one or two" in response.text
    assert settings_store.feeds_per_day(session) == 2


def test_a_ribbon_span_off_the_list_is_refused(client, session):
    response = client.post(
        "/settings/timing", data={"ribbon_span_h": "500"}, follow_redirects=False
    )

    assert response.status_code == 400
    assert settings_store.ribbon_span_h(session) == 48


def test_a_temperature_a_starter_would_not_survive_is_refused(client, session):
    response = client.post(
        "/settings/timing", data={"ferment_temp": "400"}, follow_redirects=False
    )

    assert response.status_code == 400
    assert settings_store.default_ferment_temp_c(session) == pytest.approx(26.7, abs=0.1)


def test_a_setting_hand_edited_into_nonsense_falls_back(session):
    """A bad row must not take the page down with it."""
    settings_store.set_setting(session, "feeds_per_day", "banana")
    settings_store.set_setting(session, "default_ferment_temp_c", "warm")
    session.commit()

    assert settings_store.feeds_per_day(session) == 2
    assert settings_store.default_ferment_temp_c(session) == pytest.approx(26.7, abs=0.1)


# --- Busy blocks --------------------------------------------------------


def test_a_weekly_block_can_be_added(client, session):
    response = client.post(
        "/settings/busy",
        data={
            "kind": "recurring",
            "label": "Sleep",
            "start_minute": "02:00",
            "end_minute": "10:00",
            "weekdays": ["0", "1", "2", "3", "4", "5", "6"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    blocks = busy_service.list_blocks(session)
    assert len(blocks) == 1
    assert blocks[0].label == "Sleep"
    assert blocks[0].weekday_mask == EVERY_DAY
    assert (blocks[0].start_minute, blocks[0].end_minute) == (120, 600)


def test_only_the_days_that_were_ticked_are_kept(client, session):
    client.post(
        "/settings/busy",
        data={
            "kind": "recurring", "label": "Work",
            "start_minute": "09:00", "end_minute": "17:00",
            "weekdays": ["0", "1", "2", "3", "4"],
        },
    )

    assert busy_service.list_blocks(session)[0].weekday_mask == WEEKDAYS


def test_a_block_on_no_days_is_refused(client, session):
    response = client.post(
        "/settings/busy",
        data={
            "kind": "recurring", "label": "Nothing",
            "start_minute": "09:00", "end_minute": "17:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "at least one day" in response.text
    assert busy_service.list_blocks(session) == []


def test_a_block_with_no_name_is_refused(client, session):
    response = client.post(
        "/settings/busy",
        data={
            "kind": "recurring", "label": "  ",
            "start_minute": "09:00", "end_minute": "17:00",
            "weekdays": ["0"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "needs a name" in response.text
    assert busy_service.list_blocks(session) == []


def test_a_one_off_block_is_read_in_the_local_zone_and_stored_in_utc(
    client, session
):
    response = client.post(
        "/settings/busy",
        data={
            "kind": "once",
            "label": "Out all day",
            "start_utc": "2026-06-04T09:00",
            "end_utc": "2026-06-04T17:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    block = busy_service.list_blocks(session)[0]
    # 09:00 America/New_York in June is 13:00 UTC.
    assert block.start_utc == datetime(2026, 6, 4, 13, 0, tzinfo=UTC)
    assert block.end_utc == datetime(2026, 6, 4, 21, 0, tzinfo=UTC)
    assert block.kind is BusyKind.ONCE


def test_a_one_off_block_that_ends_before_it_starts_is_refused(client, session):
    response = client.post(
        "/settings/busy",
        data={
            "kind": "once", "label": "Backwards",
            "start_utc": "2026-06-04T17:00", "end_utc": "2026-06-04T09:00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "end after it starts" in response.text
    assert busy_service.list_blocks(session) == []


def test_a_block_can_be_edited(client, session):
    client.post(
        "/settings/busy",
        data={
            "kind": "recurring", "label": "Sleep",
            "start_minute": "02:00", "end_minute": "10:00",
            "weekdays": ["0"],
        },
    )
    block = busy_service.list_blocks(session)[0]

    client.post(
        f"/settings/busy/{block.id}/edit",
        data={
            "kind": "recurring", "label": "Sleep in",
            "start_minute": "03:00", "end_minute": "11:30",
            "weekdays": ["5", "6"],
        },
    )
    session.expire_all()

    changed = busy_service.list_blocks(session)[0]
    assert changed.label == "Sleep in"
    assert (changed.start_minute, changed.end_minute) == (180, 690)
    assert changed.weekdays == (5, 6)


def test_a_block_is_archived_never_deleted(client, session):
    session.add(
        BusyBlock(
            label="Sleep", kind=BusyKind.RECURRING,
            weekday_mask=EVERY_DAY, start_minute=120, end_minute=600,
        )
    )
    session.commit()
    block = busy_service.list_blocks(session)[0]

    client.post(f"/settings/busy/{block.id}/archive")
    session.expire_all()

    assert busy_service.list_blocks(session) == []
    kept = busy_service.list_blocks(session, include_archived=True)
    assert len(kept) == 1 and kept[0].archived


def test_an_archived_block_can_be_restored(client, session):
    session.add(
        BusyBlock(
            label="Sleep", kind=BusyKind.RECURRING, archived=True,
            weekday_mask=EVERY_DAY, start_minute=120, end_minute=600,
        )
    )
    session.commit()
    block = busy_service.list_blocks(session, include_archived=True)[0]

    client.post(f"/settings/busy/{block.id}/archive", data={"restore": "1"})
    session.expire_all()

    assert len(busy_service.list_blocks(session)) == 1


def test_editing_a_block_that_is_not_there_is_a_404(client):
    response = client.post(
        "/settings/busy/9999/edit",
        data={
            "kind": "recurring", "label": "Ghost",
            "start_minute": "01:00", "end_minute": "02:00", "weekdays": ["0"],
        },
    )

    assert response.status_code == 404


def test_the_blocks_show_up_on_the_page_with_their_schedule(client, session):
    session.add(
        BusyBlock(
            label="Sleep", kind=BusyKind.RECURRING,
            weekday_mask=EVERY_DAY, start_minute=120, end_minute=600,
        )
    )
    session.commit()

    page = client.get("/settings")

    assert "Sleep" in page.text
    assert "Every day 02:00–10:00" in page.text


# --- The per-jar rhythm override ----------------------------------------


def test_a_jar_follows_the_app_setting_by_default(session):
    jar = _jar(session)

    assert jar.feeds_per_day is None
    assert settings_store.jar_feeds_per_day(session, jar) == 2


def test_a_jar_can_be_put_on_its_own_rhythm(session):
    jar = _jar(session, feeds_per_day=1)

    assert settings_store.jar_feeds_per_day(session, jar) == 1


def test_changing_the_app_setting_moves_the_jars_that_follow_it(session):
    following = _jar(session)
    own = _jar(session, feeds_per_day=1)
    settings_store.set_setting(session, "feeds_per_day", "1")
    session.commit()

    assert settings_store.jar_feeds_per_day(session, following) == 1
    assert settings_store.jar_feeds_per_day(session, own) == 1

    settings_store.set_setting(session, "feeds_per_day", "2")
    session.commit()

    assert settings_store.jar_feeds_per_day(session, following) == 2
    assert settings_store.jar_feeds_per_day(session, own) == 1


def test_the_jar_form_offers_the_rhythm(client, session):
    jar = _jar(session)

    page = client.get(f"/jars/{jar.id}/edit")

    assert page.status_code == 200
    assert "Feeds a day" in page.text
    assert "the app&#39;s setting" in page.text or "the app's setting" in page.text


def test_the_jar_form_saves_a_rhythm_and_can_clear_it(client, session):
    jar = _jar(session)
    base = {
        "name": "Old Rye", "origin": "homemade", "state": "active",
        "feed_interval_room_h": "12", "feed_interval_fridge_h": "168",
    }

    client.post(f"/jars/{jar.id}/edit", data={**base, "feeds_per_day": "1"})
    session.expire_all()
    assert session.get(Jar, jar.id).feeds_per_day == 1

    # Back to following the app: the blank option is a real choice.
    client.post(f"/jars/{jar.id}/edit", data={**base, "feeds_per_day": ""})
    session.expire_all()
    assert session.get(Jar, jar.id).feeds_per_day is None


def test_a_rhythm_nobody_feeds_at_is_refused_on_the_jar_too(client, session):
    jar = _jar(session)

    response = client.post(
        f"/jars/{jar.id}/edit",
        data={
            "name": "Old Rye", "origin": "homemade", "state": "active",
            "feeds_per_day": "7",
            "feed_interval_room_h": "12", "feed_interval_fridge_h": "168",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    session.expire_all()
    assert session.get(Jar, jar.id).feeds_per_day is None


def test_a_new_jar_can_be_given_a_rhythm_at_birth(client, session):
    response = client.post(
        "/jars/new",
        data={
            "name": "Slow jar", "origin": "homemade", "state": "active",
            "feeds_per_day": "1",
            "feed_interval_room_h": "12", "feed_interval_fridge_h": "168",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    made = session.query(Jar).filter(Jar.name == "Slow jar").one()
    assert made.feeds_per_day == 1
