"""The ribbon on a page, and moving a planned feed from one.

Phase B's acceptance checks live here: the ribbon renders for both jars at
phone and desktop width, moving a planned feed shifts all the later ones, a
late feed offers both choices, and the alert follows the plan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.alert import Alert
from app.models.busy_block import EVERY_DAY, BusyBlock
from app.models.enums import BusyKind, JarOrigin, JarState
from app.models.feeding import Feeding
from app.models.jar import Jar
from app.models.observation import Observation
from app.services import alerts as alert_service
from app.services import plan as plan_service
from app.services import ribbon as ribbon_service
from app.services.units import f_to_c


def _jar(session, name="Old Rye", **fields) -> Jar:
    jar = Jar(name=name, origin=JarOrigin.HOMEMADE, **fields)
    session.add(jar)
    session.commit()
    return jar


def _feed(session, jar, *, at, starter=20.0, flour=40.0, water=40.0, temp_c=None):
    session.add(
        Feeding(
            jar_id=jar.id, fed_at=at, starter_g=starter,
            flour_g=flour, water_g=water, ambient_temp_c=temp_c,
        )
    )
    session.commit()


def _sleep_block(session, label="Sleep", start_min=120, end_min=600):
    session.add(
        BusyBlock(
            label=label, kind=BusyKind.RECURRING, weekday_mask=EVERY_DAY,
            start_minute=start_min, end_minute=end_min,
        )
    )
    session.commit()


def _hours_ago(hours):
    from app.models.base import utcnow

    return utcnow() - timedelta(hours=hours)


def _release(session):
    """Let go of the read transaction before the client writes.

    Touching an attribute after a commit re-loads it, which opens a read
    transaction that SQLite will not let the request's own session write
    underneath. Ending it here is the difference between a passing test and
    "database is locked".
    """
    session.rollback()


# --- It renders ---------------------------------------------------------


def test_the_dashboard_draws_a_ribbon_for_both_jars(client, session):
    homemade = _jar(session, name="Old Rye")
    control = _jar(session, name="Soviet rye", is_control=True)
    _feed(session, homemade, at=_hours_ago(4))
    _feed(session, control, at=_hours_ago(7))

    page = client.get("/")

    assert page.status_code == 200
    assert 'class="ribbon fit fit-360"' in page.text
    assert "Old Rye" in page.text and "Soviet rye" in page.text
    # One row each, sharing the one axis — in every width it is drawn at.
    assert page.text.count('class="ribbon-row') == 2 * len(ribbon_service.SIZES)


def test_the_jar_page_draws_its_own_ribbon(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    page = client.get(f"/jars/{jar.id}")

    assert page.status_code == 200
    assert 'class="ribbon fit fit-360"' in page.text
    assert page.text.count('class="ribbon-row') == len(ribbon_service.SIZES)


def test_the_ribbon_is_drawn_at_every_width_and_fixed_to_none(client, session):
    """Stretching one drawing to fit made the type three times too big on a
    desktop and too small to read on a phone. So it is drawn once per width
    in `SIZES` and the stylesheet shows the nearest — each still a viewBox
    with no width attribute, so each still flexes the little it has to.
    """
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    page = client.get(f"/jars/{jar.id}")

    for width in ribbon_service.SIZES:
        marker = f'class="ribbon fit fit-{width:g}" viewBox="0 0 {width:g} '
        assert marker in page.text
        svg = page.text.split(marker)[1][:200]
        assert "width=" not in svg
    assert 'class="chart-fit"' in page.text


def test_a_wider_ribbon_spends_its_width_on_time(session):
    """More room means more clock labels, not bigger ones."""
    now = datetime.now(UTC)
    drawn = ribbon_service.ribbon(
        [ribbon_service.RibbonSeries(name="Rye", jar_id=1)],
        start=now, end=now + timedelta(hours=48), now=now, tz=UTC,
    )

    widths = [one.width for one in drawn.sizes]
    ticks = [len(one.ticks) for one in drawn.sizes]

    assert tuple(widths) == ribbon_service.SIZES
    assert ticks == sorted(ticks) and ticks[-1] > ticks[0]
    # The rows are the same height in every one of them.
    assert len({one.plot.h for one in drawn.sizes}) == 1


def test_a_jar_never_fed_still_appears_on_the_ribbon(client, session):
    _jar(session)

    page = client.get("/")

    assert 'class="ribbon fit fit-360"' in page.text
    assert "Never fed" in page.text


def test_the_ribbon_draws_the_rise_curve_in_bands(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(3), starter=20, flour=20, water=20,
          temp_c=f_to_c(78.0))

    page = client.get(f"/jars/{jar.id}")

    assert "ribbon-path band-" in page.text


def test_a_fed_again_jar_draws_one_hump_per_cycle_not_two_over_each_other(
    client, session
):
    """The earlier curve stops at the later feed instead of running past it.

    Both feeds are inside the window, so both are drawn — but the first one
    was overtaken four hours into a five-hour rise, and the peak it was
    heading for never happened.
    """
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(5), starter=20, flour=20, water=20,
          temp_c=f_to_c(78.0))
    _feed(session, jar, at=_hours_ago(1), starter=20, flour=20, water=20,
          temp_c=f_to_c(78.0))

    page = client.get(f"/jars/{jar.id}")

    # Counted per drawing: the ribbon is emitted once for each width.
    drawings = len(ribbon_service.SIZES)
    assert page.text.count('class="ribbon-curve"') == 2 * drawings
    assert "before it peaked" in page.text
    # Only the cycle still running claims a peak.
    assert page.text.count('class="ribbon-peak"') == 1 * drawings


def test_the_ribbon_marks_the_feeds_with_their_ratio(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(3), starter=20, flour=100, water=100)

    page = client.get(f"/jars/{jar.id}")

    assert "1:5:5" in page.text


def test_measured_rises_show_up_as_dots_on_the_curve(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(5))
    session.add(
        Observation(
            jar_id=jar.id, observed_at=_hours_ago(2),
            start_height_mm=20.0, height_mm=40.0,
        )
    )
    session.commit()

    page = client.get(f"/jars/{jar.id}")

    assert "ribbon-obs" in page.text


def test_busy_blocks_are_shaded_on_the_ribbon(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(3))
    _sleep_block(session)

    page = client.get(f"/jars/{jar.id}")

    assert "ribbon-busy-band" in page.text
    assert "Sleep" in page.text


def test_the_span_setting_changes_how_far_the_ribbon_looks(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(3))

    client.post("/settings/timing", data={"ribbon_span_h": "72"})
    page = client.get(f"/jars/{jar.id}")

    assert "next 72 hours" in page.text


# --- Moving a planned feed ---------------------------------------------


def test_the_plan_panel_offers_the_nudges(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    page = client.get(f"/jars/{jar.id}")

    assert "Next feed" in page.text
    for label in ("−1 h", "−30 m", "+30 m", "+1 h"):
        assert label in page.text


def test_nudging_moves_the_next_feed_and_every_later_one(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))
    now = datetime.now(UTC)
    until = now + timedelta(days=3)

    before = [
        one.at
        for one in plan_service.jar_plan(session, jar, now=now, until=until).planned
    ]
    jar_id = jar.id
    _release(session)
    client.post(f"/jars/{jar_id}/plan/nudge", data={"minutes": "-60"})
    session.expire_all()
    after = [
        one.at
        for one in plan_service.jar_plan(
            session, session.get(Jar, jar_id), now=now, until=until
        ).planned
    ]

    assert len(before) == len(after)
    offsets = {later - earlier for earlier, later in zip(before, after)}
    assert offsets == {timedelta(hours=-1)}


def test_moving_a_feed_to_a_chosen_time_sticks(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))
    target = (datetime.now(UTC) + timedelta(hours=10)).replace(
        minute=0, second=0, microsecond=0
    )
    jar_id = jar.id
    _release(session)

    client.post(
        f"/jars/{jar_id}/plan/move",
        data={"at": target.astimezone(
            __import__("zoneinfo").ZoneInfo("America/New_York")
        ).strftime("%Y-%m-%dT%H:%M")},
    )
    session.expire_all()

    assert session.get(Jar, jar_id).schedule_anchor_utc == target


def test_a_moved_plan_can_be_put_back_on_the_usual_rhythm(client, session):
    jar = _jar(session, schedule_anchor_utc=datetime.now(UTC))
    _feed(session, jar, at=_hours_ago(4))
    jar_id = jar.id
    _release(session)

    client.post(f"/jars/{jar_id}/plan/reset")
    session.expire_all()

    assert session.get(Jar, jar_id).schedule_anchor_utc is None


def test_nudging_swaps_the_panel_back_in_for_htmx(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    response = client.post(
        f"/jars/{jar.id}/plan/nudge",
        data={"minutes": "-60"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'id="feed-plan"' in response.text
    # The panel only, not the whole page.
    assert "<html" not in response.text


def test_a_plain_post_redirects_back_to_the_jar(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    response = client.post(
        f"/jars/{jar.id}/plan/nudge", data={"minutes": "-60"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/jars/{jar.id}"


def test_a_nonsense_nudge_changes_nothing(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))

    jar_id = jar.id
    _release(session)

    client.post(f"/jars/{jar_id}/plan/nudge", data={"minutes": "banana"})

    assert session.get(Jar, jar_id).schedule_anchor_utc is None


def test_moving_a_feed_on_a_jar_that_is_not_there_is_a_404(client):
    assert client.post("/jars/9999/plan/nudge", data={"minutes": "60"}).status_code == 404


# --- Busy-block overlap ------------------------------------------------


def test_a_feed_planned_in_the_small_hours_is_flagged_with_a_way_out(
    client, session
):
    """The problem the whole feature exists for: a feed landing at 04:00."""
    jar = _jar(session)
    _sleep_block(session)  # 02:00-10:00 local, every day
    _feed(session, jar, at=_hours_ago(4))

    # Put the next feed squarely inside the block: 04:00 local tomorrow.
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    target = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    jar_id = jar.id
    _release(session)
    client.post(
        f"/jars/{jar_id}/plan/move",
        data={"at": target.strftime("%Y-%m-%dT%H:%M")},
    )

    page = client.get(f"/jars/{jar_id}")

    assert "That lands in Sleep" in page.text
    assert "The first clear time is" in page.text
    # And the way out is one click, with the ratio to match.
    assert "Move to 10:00" in page.text


def test_the_suggested_move_lands_outside_the_block(client, session):
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session)
    _sleep_block(session)
    _feed(session, jar, at=_hours_ago(4))

    target = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    client.post(
        f"/jars/{jar.id}/plan/move", data={"at": target.strftime("%Y-%m-%dT%H:%M")}
    )
    session.expire_all()

    made = plan_service.jar_plan(
        session, session.get(Jar, jar.id),
        now=datetime.now(UTC), until=datetime.now(UTC) + timedelta(days=3),
    )
    from app.services import busy as busy_service

    now = datetime.now(UTC)
    intervals = busy_service.busy_intervals(
        session, now, now + timedelta(days=3), tz
    )
    free = busy_service.next_free(intervals, made.next_feed_at)
    assert free is not None
    assert not busy_service.is_busy(intervals, free)


def test_a_feed_planned_in_the_clear_is_not_flagged(client, session):
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session)
    _sleep_block(session)
    _feed(session, jar, at=_hours_ago(4))

    target = (datetime.now(tz) + timedelta(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    client.post(
        f"/jars/{jar.id}/plan/move", data={"at": target.strftime("%Y-%m-%dT%H:%M")}
    )

    page = client.get(f"/jars/{jar.id}")

    assert "That lands in" not in page.text


# --- A late feed offers both choices -----------------------------------


def test_a_late_feed_offers_both_choices(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(20))  # 12 h cycle, so 8 h late

    page = client.get(f"/jars/{jar.id}/feed")

    assert "Keep my usual times" in page.text
    assert "Shift my schedule" in page.text
    assert "late" in page.text


def test_keeping_usual_times_is_the_default(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(20))

    page = client.get(f"/jars/{jar.id}/feed")

    keep = page.text.split('value="keep"')[1][:40]
    assert "checked" in keep


def test_an_on_time_feed_is_not_asked_about(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(12))  # bang on a 12 h cycle

    page = client.get(f"/jars/{jar.id}/feed")

    assert "Shift my schedule" not in page.text


def test_keeping_usual_times_leaves_the_rhythm_alone(client, session):
    jar = _jar(session)
    first = _hours_ago(20)
    _feed(session, jar, at=first)
    jar_id = jar.id
    _release(session)

    client.post(
        f"/jars/{jar_id}/feed",
        data={
            "starter_g": "20", "flour_g": "40", "water_g": "40",
            "schedule_choice": "keep",
        },
    )
    session.expire_all()

    anchor = session.get(Jar, jar_id).schedule_anchor_utc
    # The feed that was planned was first + 12 h, so the next stays + 24 h.
    assert anchor == first + timedelta(hours=24)


def test_shifting_the_schedule_follows_the_feed(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(20))

    before = datetime.now(UTC)
    jar_id = jar.id
    _release(session)
    client.post(
        f"/jars/{jar_id}/feed",
        data={
            "starter_g": "20", "flour_g": "40", "water_g": "40",
            "schedule_choice": "shift",
        },
    )
    session.expire_all()

    anchor = session.get(Jar, jar_id).schedule_anchor_utc
    assert anchor is not None
    # Roughly 12 h from the feed that was just logged.
    assert abs((anchor - before) - timedelta(hours=12)) < timedelta(minutes=2)


def test_the_feed_form_suggests_a_ratio_to_land_the_next_peak(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4), temp_c=f_to_c(80.0))

    page = client.get(f"/jars/{jar.id}/feed")

    assert "To peak at the right time" in page.text
    assert "Next feed is planned for" in page.text
    assert "Advice, not a default" in page.text


def test_the_suggestion_does_not_fill_the_amounts_in(client, session):
    """It is advice: the amounts stay whatever was fed last time."""
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4), starter=20, flour=40, water=40)

    page = client.get(f"/jars/{jar.id}/feed")

    starter = page.text.split('name="starter_g"')[1][:160]
    assert 'value="20"' in starter


# --- The alert follows the plan ----------------------------------------


def test_the_alert_fires_on_the_planned_feed_not_the_fixed_interval(session):
    jar = _jar(session, feed_interval_room_h=8)
    _feed(session, jar, at=_hours_ago(10))
    now = datetime.now(UTC)

    alert_service.reconcile(session, now)

    alerts = session.query(Alert).all()
    assert len(alerts) == 1
    # The 8 h interval would have been due two hours ago; the 12 h cycle is
    # what the plan says, so that is what the alert is for.
    assert abs(alerts[0].due_at - (_hours_ago(10) + timedelta(hours=12))) < timedelta(
        minutes=1
    )


def test_moving_a_feed_moves_the_alert_with_it(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))
    now = datetime.now(UTC)
    alert_service.reconcile(session, now)
    session.commit()
    before = session.query(Alert).one().due_at
    jar_id = jar.id
    _release(session)

    client.post(f"/jars/{jar_id}/plan/nudge", data={"minutes": "-60"})

    after = session.query(Alert).one().due_at
    assert after == before - timedelta(hours=1)


def test_a_jar_never_fed_still_has_no_alert(session):
    _jar(session)

    alert_service.reconcile(session, datetime.now(UTC))

    assert session.query(Alert).all() == []


def test_a_fridge_jar_keeps_its_own_interval(session):
    jar = _jar(session, state=JarState.FRIDGE, feed_interval_fridge_h=168)
    fed = _hours_ago(10)
    _feed(session, jar, at=fed)

    alert_service.reconcile(session, datetime.now(UTC))

    alert = session.query(Alert).one()
    assert abs(alert.due_at - (fed + timedelta(hours=168))) < timedelta(minutes=1)


def test_reconcile_stays_idempotent_with_a_plan(session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(4))
    now = datetime.now(UTC)

    alert_service.reconcile(session, now)
    first = {(a.jar_id, a.due_at) for a in session.query(Alert).all()}
    for _ in range(3):
        alert_service.reconcile(session, now)

    assert {(a.jar_id, a.due_at) for a in session.query(Alert).all()} == first
    assert session.query(Alert).count() == 1


def test_an_overdue_jar_is_reported_overdue_on_the_card(session):
    """The regression that matters: a plan must not hide an owed feed."""
    from app.services import jars as jar_service

    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(20))

    card = jar_service.jar_card(session, jar, datetime.now(UTC))

    assert card.status.is_overdue
    assert card.status.overdue_by >= timedelta(hours=7)


def test_a_move_too_far_for_any_ratio_says_so_instead_of_suggesting_one(
    client, session
):
    """A ratio the peak cannot reach is worse than no ratio at all.

    Moving a 04:00 feed to 10:00 is often sixteen hours out from now, and
    nothing feedable stretches that far at proofing-box temperature. The
    badge drops the number and the panel explains.
    """
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session)
    _sleep_block(session)
    _feed(session, jar, at=_hours_ago(1))
    jar_id = jar.id
    _release(session)

    # Two days out, well past anything a feedable ratio reaches.
    target = (datetime.now(tz) + timedelta(days=2)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    client.post(
        f"/jars/{jar_id}/plan/move",
        data={"at": target.strftime("%Y-%m-%dT%H:%M")},
    )

    page = client.get(f"/jars/{jar_id}")

    assert "That lands in Sleep" in page.text
    assert "The closest a feedable ratio gets" in page.text
    assert "Somewhere cooler" in page.text


# --- Head to head ---------------------------------------------------------
#
# Asked for, about jars you pick: "Add to comparison" on a jar's page puts
# it on a list, and /compare draws the list on one axis.


def _compare(client, *jar_ids):
    for jar_id in jar_ids:
        client.post(f"/compare/{jar_id}/add")


def test_the_dashboard_no_longer_sets_jars_head_to_head(client, session):
    one = _jar(session, name="Homemade", flour_type="whole rye")
    two = _jar(session, name="Bought", flour_type="Whole Rye")
    for jar in (one, two):
        _feed(session, jar, at=_hours_ago(2))
    _release(session)

    assert 'data-chart="duel"' not in client.get("/").text


def test_the_comparison_draws_the_jars_that_were_picked(client, session):
    one = _jar(session, name="Homemade", flour_type="whole rye")
    two = _jar(session, name="Bought", flour_type="Whole Rye")
    other = _jar(session, name="Wheat", flour_type="bread flour")
    for jar in (one, two, other):
        _feed(session, jar, at=_hours_ago(2))
    ids = (one.id, two.id)
    _release(session)

    _compare(client, *ids)
    page = client.get("/compare")

    assert 'data-chart="duel"' in page.text
    # The two that were picked, in every width; the third was not asked for.
    rows = page.text.count('class="duel-row')
    assert rows == 2 * len(ribbon_service.SIZES)
    assert "same flour, same clock" in page.text


def test_jars_on_different_flours_can_be_compared_and_it_says_so(client, session):
    rye = _jar(session, name="Rye", flour_type="rye")
    wheat = _jar(session, name="Wheat", flour_type="wheat")
    for jar in (rye, wheat):
        _feed(session, jar, at=_hours_ago(2))
    ids = (rye.id, wheat.id)
    _release(session)

    _compare(client, *ids)
    page = client.get("/compare").text

    assert 'data-chart="duel"' in page
    assert "same flour, same clock" not in page
    assert "same clock" in page


def test_one_jar_is_not_a_comparison(client, session):
    jar = _jar(session, name="Rye", flour_type="rye")
    _feed(session, jar, at=_hours_ago(2))
    jar_id = jar.id
    _release(session)

    _compare(client, jar_id)
    page = client.get("/compare").text

    assert 'data-chart="duel"' not in page
    assert "One more to compare it with" in page


def test_head_to_head_does_not_claim_a_peak_the_next_feed_pre_empted(
    client, session
):
    """Fed twice an hour apart: the first cycle never got to its peak, so
    only the second gets a peak marker on the overlay."""
    jars = [
        _jar(session, name="Homemade", flour_type="rye"),
        _jar(session, name="Bought", flour_type="rye"),
    ]
    for jar in jars:
        _feed(session, jar, at=_hours_ago(2))
        _feed(session, jar, at=_hours_ago(1))
    ids = [jar.id for jar in jars]
    _release(session)

    _compare(client, *ids)
    page = client.get("/compare")

    peaks = page.text.count('class="duel-peak"')
    assert peaks == len(ids) * len(ribbon_service.SIZES)


def test_a_hungry_jar_s_row_says_it_is_waiting(client, session):
    """Fed a day and a half ago: the curve is long gone from the window, and
    the row used to be empty but for the planned feeds."""
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(36), starter=20, flour=20, water=20,
          temp_c=f_to_c(78.0))

    page = client.get(f"/jars/{jar.id}")

    assert page.text.count('class="ribbon-wait"') == len(ribbon_service.SIZES)
    assert "hungry since" in page.text.lower()


def test_a_freshly_fed_jar_s_row_does_not(client, session):
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(1))

    assert 'class="ribbon-wait"' not in client.get(f"/jars/{jar.id}").text


# --- The next feed, however far off --------------------------------------


def test_a_feed_moved_past_the_ribbon_is_still_the_next_feed(session):
    """At every hour of the day.

    The route test above moves a feed to four in the morning two days out,
    by the real clock. Run between midnight and four, that is more than the
    ribbon's forty-eight hours away, and the plan used to come back empty:
    the page said "nothing planned yet" about a feed it had just been told
    to plan, and the test failed for four hours a night. A plan now always
    names its next feed, and this holds it to that around the clock.
    """
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session)
    for hour in range(24):
        for minute in (0, 1, 59):
            now_local = datetime(2026, 11, 27, hour, minute, tzinfo=tz)
            now = now_local.astimezone(UTC)
            target = (now_local + timedelta(days=2)).replace(
                hour=4, minute=0, second=0, microsecond=0
            ).astimezone(UTC)
            plan_service.move_next_feed(session, jar, to=target, now=now)

            feeds, anchored = plan_service.planned_feeds(
                session, jar, now=now, until=now + timedelta(hours=48),
                last_fed_at=now - timedelta(hours=1),
            )

            assert anchored
            assert feeds, f"no plan at {hour:02d}:{minute:02d}"
            assert feeds[0].at == target, f"{hour:02d}:{minute:02d}"


def test_a_feed_inside_the_window_is_not_joined_by_one_outside_it(session):
    """The extra feed is only ever the lone next one, never an addition."""
    jar = _jar(session)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    until = now + timedelta(hours=48)
    feeds, _ = plan_service.planned_feeds(
        session, jar, now=now, until=until, last_fed_at=now - timedelta(hours=1),
    )
    assert feeds
    assert all(feed.at <= until for feed in feeds)


def test_the_page_can_take_a_far_move_back(client, session):
    """With the plan no longer empty, the panel shows the feed and the way
    back to the usual rhythm, which is what was missing when it mattered."""
    jar = _jar(session)
    _feed(session, jar, at=_hours_ago(1))
    jar_id = jar.id
    _release(session)

    far = datetime.now(UTC) + timedelta(days=5)
    client.post(
        f"/jars/{jar_id}/plan/move", data={"at": far.strftime("%Y-%m-%dT%H:%M")}
    )
    page = client.get(f"/jars/{jar_id}").text

    assert "Nothing planned yet" not in page
    assert f"/jars/{jar_id}/plan/reset" in page


# --- What the plan would bring --------------------------------------------


def test_each_planned_feed_ahead_projects_the_last_feeds_rise(session):
    """The same jar, fed the same way on the same rhythm, does the same
    thing: each planned feed still to come carries the last real feed's
    curve, and stops where the feed after it begins."""
    jar = _jar(session, feeds_per_day=2)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    _feed(session, jar, at=now - timedelta(hours=2))
    start, end = now - timedelta(hours=6), now + timedelta(hours=48)

    series, made = plan_service.jar_series(
        session, jar, now=now, start=start, end=end
    )

    ahead = [feed for feed in made.planned if feed.at >= now]
    assert len(ahead) >= 3
    assert [mark.at for mark in series.projected] == [feed.at for feed in ahead]
    real = series.feeds[-1]
    for index, mark in enumerate(series.projected):
        assert mark.peak_h == real.peak_h
        assert mark.ratio_label == real.ratio_label
        following = ahead[index + 1].at if index + 1 < len(ahead) else None
        assert mark.ends_at == following
    # History is untouched: the projections are not feeds.
    assert all(mark.at <= now for mark in series.feeds)


def test_a_missed_feed_projects_nothing_from_itself(session):
    """A planned feed already in the past set nothing off."""
    jar = _jar(session, feeds_per_day=2)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    _feed(session, jar, at=now - timedelta(hours=20))
    series, made = plan_service.jar_series(
        session, jar, now=now,
        start=now - timedelta(hours=6), end=now + timedelta(hours=48),
    )

    assert any(feed.at < now for feed in made.planned)
    assert all(mark.at >= now for mark in series.projected)


def test_a_jar_never_fed_projects_nothing(session):
    jar = _jar(session)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    series, _ = plan_service.jar_series(
        session, jar, now=now,
        start=now - timedelta(hours=6), end=now + timedelta(hours=48),
    )
    assert series.projected == ()


def test_the_ribbon_draws_projections_dashed_and_the_duel_does_not(client, session):
    first = _jar(session, name="Old Rye", flour_type="whole rye")
    second = _jar(session, name="Soviet rye", flour_type="whole rye", is_control=True)
    _feed(session, first, at=_hours_ago(2))
    _feed(session, second, at=_hours_ago(2))
    _release(session)

    page = client.get("/").text

    ribbon_card = page.split('data-chart="ribbon"')[1].split("</figure>")[0]
    assert 'class="ribbon-curve is-projected"' in ribbon_card
    assert "If fed as planned at" in ribbon_card
    assert page.count("is-projected") == ribbon_card.count("is-projected")


# --- The wait between one rise and the next -------------------------------


def test_the_gap_before_each_planned_feed_is_drawn_as_hungry(session):
    """A rise that gives out before the next feed leaves the jar waiting.
    That stretch is drawn, ahead of now as well as behind it, so the space
    between a curve and the projection after it is never just blank."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session, feeds_per_day=1)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    # A quick 1:1 feed on a once-a-day rhythm: spent long before the next.
    _feed(session, jar, at=now - timedelta(hours=2), starter=40.0, flour=40.0, water=40.0)

    drawn, plans = plan_service.build_ribbon(session, [jar], now=now, tz=tz, span_h=48)
    row = drawn.rows[0]

    assert row.projections, "nothing projected, so nothing to check against"
    assert row.waits
    first = row.waits[0]
    next_feed = plans[jar.id].next_feed_at
    assert first.since >= now
    assert first.until == next_feed
    assert first.x1 < first.x2
    # Each wait ends where a projection begins, or at the edge of the chart.
    starts = {round(curve.x, 2) for curve in row.projections}
    for wait in row.waits:
        if wait.until is not None and wait.until <= drawn.end:
            assert round(wait.x2, 2) in starts


def test_a_rise_that_lasts_until_the_next_feed_has_no_wait(session):
    """Fed often enough, the jar is never spent before it is fed again."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo("America/New_York")
    jar = _jar(session, feeds_per_day=2)
    now = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)
    # A stiff 1:10 feed takes far longer than twelve hours to run its course.
    _feed(session, jar, at=now - timedelta(hours=1), starter=10.0, flour=100.0, water=100.0)

    drawn, _ = plan_service.build_ribbon(session, [jar], now=now, tz=tz, span_h=48)

    assert drawn.rows[0].waits == ()


def test_the_page_says_how_long_the_wait_is(client, session):
    jar = _jar(session, feeds_per_day=1)
    _feed(session, jar, at=_hours_ago(2), starter=40.0, flour=40.0, water=40.0)
    _release(session)

    page = client.get("/").text

    assert 'class="ribbon-wait is-projected"' in page
    assert "until the feed planned at" in page
