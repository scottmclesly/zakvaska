"""Busy blocks expanded into instants, daylight saving and all.

The DST tests are the point of this file. A recurring block is a wall-clock
pattern, so on the Sunday the clocks go forward "02:00–10:00" is seven hours
of real time and on the Sunday they go back it is nine. Getting that wrong
would put a shaded stripe an hour off the sleep it stands for, twice a year,
which is the sort of bug that gets blamed on the starter.

America/New_York, which is ZAKVASKA_TZ in the tests:
  forward  2026-03-08 02:00 EST -> 03:00 EDT   (02:00–02:59 does not exist)
  back     2026-11-01 02:00 EDT -> 01:00 EST   (01:00–01:59 happens twice)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.busy_block import (
    EVERY_DAY,
    SUNDAY,
    WEEKDAYS,
    BusyBlock,
    minutes_label,
    weekday_label,
)
from app.models.enums import BusyKind
from app.services import busy

TZ = ZoneInfo("America/New_York")


def _sleep(session, start="02:00", end="10:00", days=EVERY_DAY, label="Sleep"):
    hour, minute = (int(part) for part in start.split(":"))
    end_hour, end_minute = (int(part) for part in end.split(":"))
    block = BusyBlock(
        label=label,
        kind=BusyKind.RECURRING,
        weekday_mask=days,
        start_minute=hour * 60 + minute,
        end_minute=end_hour * 60 + end_minute,
    )
    session.add(block)
    session.flush()
    return block


def _once(session, start: datetime, end: datetime, label="Flight"):
    block = BusyBlock(
        label=label, kind=BusyKind.ONCE, start_utc=start, end_utc=end
    )
    session.add(block)
    session.flush()
    return block


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _local(block_start: datetime) -> str:
    return block_start.astimezone(TZ).strftime("%Y-%m-%d %H:%M %Z")


# --- The ordinary week --------------------------------------------------


def test_a_nightly_block_lands_at_the_same_local_time_each_day(session):
    _sleep(session)

    found = busy.busy_intervals(
        session, _utc(2026, 6, 1), _utc(2026, 6, 5), TZ
    )

    assert len(found) == 4
    for interval in found:
        local = interval.start.astimezone(TZ)
        assert (local.hour, local.minute) == (2, 0)
        assert interval.end - interval.start == timedelta(hours=8)


def test_only_the_chosen_weekdays_appear(session):
    _sleep(session, start="09:00", end="17:00", days=WEEKDAYS, label="Work")

    # A full week starting on a Monday.
    found = busy.busy_intervals(
        session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ
    )

    assert [one.start.astimezone(TZ).strftime("%a") for one in found] == [
        "Mon", "Tue", "Wed", "Thu", "Fri",
    ]


def test_a_block_is_labelled_so_the_ribbon_can_say_which_it_is(session):
    _sleep(session, label="Asleep")
    _sleep(session, start="14:00", end="18:00", days=SUNDAY, label="Dinner")

    found = busy.busy_intervals(
        session, _utc(2026, 6, 7), _utc(2026, 6, 8), TZ
    )

    assert {one.label for one in found} == {"Asleep", "Dinner"}


def test_overlapping_blocks_are_kept_apart_rather_than_merged(session):
    _sleep(session, start="02:00", end="10:00", label="Sleep")
    _sleep(session, start="09:00", end="17:00", label="Work")

    found = busy.busy_intervals(
        session, _utc(2026, 6, 1), _utc(2026, 6, 2), TZ
    )

    # Two reasons to be unavailable, and the ribbon shows both.
    assert sorted(one.label for one in found) == ["Sleep", "Work"]


def test_an_archived_block_stops_shading_the_ribbon(session):
    block = _sleep(session)
    block.archived = True
    session.flush()

    assert busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 5), TZ) == []


def test_a_block_on_no_days_at_all_covers_nothing(session):
    _sleep(session, days=0)

    assert busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ) == []


# --- Wrapping past midnight ---------------------------------------------


def test_a_block_can_run_past_midnight_into_the_next_day(session):
    _sleep(session, start="22:00", end="06:00")

    found = busy.busy_intervals(
        session, _utc(2026, 6, 2), _utc(2026, 6, 3), TZ
    )

    assert found
    for interval in found:
        assert interval.end - interval.start == timedelta(hours=8)
        assert interval.start.astimezone(TZ).hour == 22
        assert interval.end.astimezone(TZ).hour == 6


def test_a_block_started_yesterday_still_covers_this_morning(session):
    # Saturday night into Sunday morning; the window opens on the Sunday.
    _sleep(session, start="23:00", end="07:00", label="Sleep")

    found = busy.busy_intervals(
        # 2026-06-07 is a Sunday. 08:00 UTC is 04:00 local, mid-block.
        session, _utc(2026, 6, 7, 8), _utc(2026, 6, 7, 9), TZ
    )

    assert len(found) == 1
    assert busy.is_busy(found, _utc(2026, 6, 7, 8, 30))


def test_equal_start_and_end_means_the_whole_day_not_nothing(session):
    block = _sleep(session, start="09:00", end="09:00", days=SUNDAY)

    assert block.duration_min == 24 * 60

    found = busy.busy_intervals(
        session, _utc(2026, 6, 7), _utc(2026, 6, 9), TZ
    )

    assert len(found) == 1
    assert found[0].end - found[0].start == timedelta(days=1)


# --- Daylight saving ----------------------------------------------------


def test_the_sunday_the_clocks_go_forward_is_an_hour_shorter(session):
    """02:00–10:00 on 2026-03-08, when 02:00 itself does not exist.

    The clock jumps 02:00 EST to 03:00 EDT, so getting from "two" to "ten"
    takes seven hours of real time. Scott loses an hour of sleep and the
    shaded stripe is an hour narrower, which is the truth of that morning.
    """
    _sleep(session)

    found = busy.busy_intervals(
        session, _utc(2026, 3, 8), _utc(2026, 3, 9), TZ
    )

    assert len(found) == 1
    interval = found[0]
    assert interval.end - interval.start == timedelta(hours=7), _local(
        interval.start
    )
    # It still ends when the clock says ten, which is what matters.
    assert interval.end.astimezone(TZ).hour == 10


def test_the_sunday_the_clocks_go_back_leaves_a_two_to_ten_night_alone(session):
    """02:00–10:00 on 2026-11-01 is an ordinary eight hours.

    Worth pinning precisely because it is the case that looks like it should
    change and does not: the hour that happens twice is 01:00–01:59, which is
    over before this block starts. Only a block that is already running at
    01:00 gets longer — see the 22:00 one below.
    """
    _sleep(session)

    found = busy.busy_intervals(
        session, _utc(2026, 11, 1), _utc(2026, 11, 2), TZ
    )

    assert len(found) == 1
    interval = found[0]
    assert interval.end - interval.start == timedelta(hours=8), _local(
        interval.start
    )
    assert interval.start.astimezone(TZ).hour == 2
    assert interval.end.astimezone(TZ).hour == 10


def test_a_night_that_is_already_running_when_the_clocks_go_back_is_longer(session):
    """22:00 Saturday to 06:00 Sunday, over the hour that happens twice.

    Nine hours of real time between "ten at night" and "six in the morning".
    The lie-in is real and the ribbon shows it.
    """
    _sleep(session, start="22:00", end="06:00")

    found = busy.busy_intervals(
        # Saturday evening into the Sunday the clocks go back.
        session, _utc(2026, 11, 1), _utc(2026, 11, 1, 12), TZ
    )

    assert len(found) == 1
    interval = found[0]
    assert interval.end - interval.start == timedelta(hours=9), _local(
        interval.start
    )
    assert interval.end.astimezone(TZ).hour == 6


def test_a_block_spanning_the_fall_back_hour_itself(session):
    """00:30–03:30 across the repeated hour: four real hours, not three."""
    _sleep(session, start="00:30", end="03:30", days=SUNDAY)

    found = busy.busy_intervals(
        session, _utc(2026, 11, 1), _utc(2026, 11, 2), TZ
    )

    assert len(found) == 1
    assert found[0].end - found[0].start == timedelta(hours=4)


def test_a_block_spanning_the_spring_forward_hour_itself(session):
    """00:30–03:30 across the missing hour: two real hours, not three."""
    _sleep(session, start="00:30", end="03:30", days=SUNDAY)

    found = busy.busy_intervals(
        session, _utc(2026, 3, 8), _utc(2026, 3, 9), TZ
    )

    assert len(found) == 1
    assert found[0].end - found[0].start == timedelta(hours=2)


def test_a_nonexistent_local_start_still_produces_a_block(session):
    """02:30 does not exist on 2026-03-08, and must not vanish.

    A block that silently disappeared on one day a year would be worse than
    one an hour out: nothing would be shaded and nothing would say why.
    """
    _sleep(session, start="02:30", end="09:00", days=SUNDAY)

    found = busy.busy_intervals(
        session, _utc(2026, 3, 8), _utc(2026, 3, 9), TZ
    )

    assert len(found) == 1
    assert found[0].end.astimezone(TZ).hour == 9


def test_a_week_across_the_change_keeps_one_block_a_day(session):
    """Seven days, seven blocks: none lost and none doubled at the change."""
    _sleep(session)

    found = busy.busy_intervals(
        session, _utc(2026, 3, 5), _utc(2026, 3, 12), TZ
    )

    starts = {one.start.astimezone(TZ).date() for one in found}
    assert len(found) == len(starts) == 7


# --- One-off blocks -----------------------------------------------------


def test_a_one_off_block_is_taken_as_the_instants_it_was_given(session):
    _once(session, _utc(2026, 6, 4, 13), _utc(2026, 6, 4, 21))

    found = busy.busy_intervals(
        session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ
    )

    assert len(found) == 1
    assert found[0].start == _utc(2026, 6, 4, 13)
    assert found[0].end == _utc(2026, 6, 4, 21)


def test_a_one_off_block_outside_the_window_is_left_out(session):
    _once(session, _utc(2026, 7, 4, 13), _utc(2026, 7, 4, 21))

    assert busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ) == []


def test_a_half_filled_one_off_block_is_ignored_rather_than_guessed_at(session):
    session.add(
        BusyBlock(label="Half", kind=BusyKind.ONCE, start_utc=_utc(2026, 6, 4))
    )
    session.flush()

    assert busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ) == []


# --- The window ---------------------------------------------------------


def test_blocks_come_back_soonest_first(session):
    _sleep(session, start="02:00", end="10:00", label="Sleep")
    _once(session, _utc(2026, 6, 1, 1), _utc(2026, 6, 1, 3), label="Flight")

    found = busy.busy_intervals(
        session, _utc(2026, 6, 1), _utc(2026, 6, 4), TZ
    )

    assert found == sorted(found, key=lambda one: one.start)


def test_a_block_touching_only_the_edge_of_the_window_is_still_reported(session):
    # 06:00–14:00 UTC on 2026-06-01 is the 02:00 local block.
    _sleep(session)

    found = busy.busy_intervals(
        session, _utc(2026, 6, 1, 13), _utc(2026, 6, 1, 15), TZ
    )

    assert len(found) == 1


def test_an_empty_table_shades_nothing(session):
    assert busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 8), TZ) == []


# --- Asking questions of them -------------------------------------------


def test_a_block_is_half_open_so_a_feed_at_the_end_is_free(session):
    _sleep(session)
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 2), TZ)
    interval = found[0]

    assert interval.covers(interval.start)
    assert not interval.covers(interval.end)


def test_next_free_hands_back_a_time_that_is_already_free(session):
    _sleep(session)
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 3), TZ)
    free = _utc(2026, 6, 1, 20)  # 16:00 local, wide awake

    assert busy.next_free(found, free) == free


def test_next_free_steps_out_to_the_end_of_the_block(session):
    _sleep(session)
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 3), TZ)

    # 08:00 UTC is 04:00 local, in the middle of Sleep.
    moved = busy.next_free(found, _utc(2026, 6, 1, 8))

    assert moved is not None
    assert moved.astimezone(TZ).hour == 10


def test_next_free_steps_clear_of_a_second_block_behind_the_first(session):
    """Waking up into work is still busy, and it must keep walking."""
    _sleep(session, start="02:00", end="10:00", label="Sleep")
    _sleep(session, start="10:00", end="18:00", label="Work")
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 3), TZ)

    moved = busy.next_free(found, _utc(2026, 6, 1, 8))

    assert moved is not None
    assert moved.astimezone(TZ).hour == 18


def test_next_free_needs_room_for_the_whole_job(session):
    _sleep(session, start="02:00", end="10:00")
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 4), TZ)

    # 01:00 local is free, but a two-hour job starting there runs into Sleep.
    start = _utc(2026, 6, 1, 5)
    assert busy.next_free(found, start) == start
    assert busy.next_free(found, start, needs=timedelta(hours=2)) != start


def test_next_free_gives_up_rather_than_lying(session):
    _sleep(session, start="00:00", end="00:00")  # busy all day, every day
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 4), TZ)

    assert busy.next_free(found, _utc(2026, 6, 1, 12), limit=_utc(2026, 6, 2)) is None


def test_overlapping_treats_an_instant_as_an_instant(session):
    _sleep(session)
    found = busy.busy_intervals(session, _utc(2026, 6, 1), _utc(2026, 6, 2), TZ)
    asleep = _utc(2026, 6, 1, 8)

    # Zero length: a ten-second hands-on step still lands inside Sleep.
    assert busy.overlapping(found, asleep, asleep)
    assert not busy.overlapping(found, _utc(2026, 6, 1, 20), _utc(2026, 6, 1, 20))


# --- Labels -------------------------------------------------------------


@pytest.mark.parametrize(
    "mask, want",
    [
        (EVERY_DAY, "Every day"),
        (WEEKDAYS, "Mon–Fri"),
        (0b1100000, "Weekends"),
        (0, "No days"),
        (0b0000001, "Mon"),
        (0b1000001, "Mon, Sun"),
    ],
)
def test_weekday_masks_read_as_words(mask, want):
    assert weekday_label(mask) == want


@pytest.mark.parametrize(
    "minutes, want",
    [(0, "00:00"), (125, "02:05"), (600, "10:00"), (1439, "23:59")],
)
def test_minutes_read_as_a_clock(minutes, want):
    assert minutes_label(minutes) == want


def test_a_block_says_its_whole_schedule_in_one_line(session):
    block = _sleep(session, start="02:00", end="10:00", label="Sleep")

    assert block.when_label == "Every day 02:00–10:00"
    assert not block.wraps_midnight


def test_a_wrapping_block_says_so(session):
    block = _sleep(session, start="22:00", end="06:00")

    assert block.wraps_midnight
    assert "next day" in block.when_label
