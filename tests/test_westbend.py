"""The West Bend L5951's own numbers, and the programs seeded from them.

The cycle data is checked against docs/reference/westbend-L5951-cycle-chart.csv,
which was in turn checked row by row against the chart on the last page of
the manual PDF in the same folder. If someone re-transcribes the CSV, this
test is what catches a slipped digit.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.data import westbend
from app.models.recipe import EquipmentCycle, EquipmentProgram
from app.services import seeding

CHART = Path("docs/reference/westbend-L5951-cycle-chart.csv")


def chart_rows() -> list[dict[str, str]]:
    lines = [
        line for line in CHART.read_text().splitlines() if not line.startswith("#")
    ]
    return list(csv.DictReader(lines))


def as_minutes(value: str) -> int | None:
    """The chart's h:mm total, or None for a range like "3:05 default"."""
    hours, _, minutes = value.partition(":")
    return int(hours or 0) * 60 + int(minutes)


def cell(value: str) -> int | None:
    """A chart cell: "x" means the program has no such phase."""
    return None if value.strip().lower() in ("x", "") else int(value)


class TestTheDataMatchesTheChart:
    def test_every_chart_row_has_a_cycle(self):
        rows = chart_rows()
        seeded = sum(len(p["cycles"]) for p in westbend.PROGRAMS)
        assert seeded == len(rows) == 28

    def test_all_twelve_programs_are_there(self):
        numbers = [p["menu_no"] for p in westbend.PROGRAMS]
        assert numbers == list(range(1, 13))

    @pytest.mark.parametrize("row", chart_rows(), ids=lambda r: f"{r['program']}-{r['loaf_lb'] or 'any'}")
    def test_the_segments_match(self, row):
        program = next(
            p for p in westbend.PROGRAMS if p["name"] == row["program"]
        )
        loaf = float(row["loaf_lb"]) if row["loaf_lb"] else None
        cycle = next(c for c in program["cycles"] if c["loaf_lb"] == loaf)

        # Custom's cells are ranges, not numbers; its ranges live in the notes.
        if row["program"] == "Custom":
            assert "3-14" in program["notes"]
            assert cycle["total_min"] == 185
            return

        assert cycle["knead1_min"] == cell(row["knead1"])
        assert cycle["rest_min"] == cell(row["rest"])
        assert cycle["knead2_min"] == cell(row["knead2"])
        assert cycle["rise2_min"] == cell(row["rise2"])
        assert cycle["rise3_min"] == cell(row["rise3"])
        if row["program"] != "Bake":  # 10-60, a range
            assert cycle["bake_min"] == cell(row["bake"])
        assert cycle["total_min"] == as_minutes(row["total_hmm"])
        assert cycle["keep_warm_min"] == cell(row["keep_warm"])
        assert cycle["delay_max_h"] == cell(row["delay_max_h"])

    def test_stir_down_is_thirty_seconds_where_the_chart_says_so(self):
        for row in chart_rows():
            program = next(
                p for p in westbend.PROGRAMS if p["name"] == row["program"]
            )
            loaf = float(row["loaf_lb"]) if row["loaf_lb"] else None
            cycle = next(c for c in program["cycles"] if c["loaf_lb"] == loaf)
            expected = 30 if "30s" in row["stir_down"] else None
            assert cycle["stir_down_sec"] == expected, row["program"]


class TestWhatTheManualSays:
    def test_the_three_loaf_sizes_are_recorded(self):
        assert westbend.LOAF_SIZES_LB == (2.0, 2.5, 3.0)
        assert "2, 2.5 and 3 lb" in westbend.SIZE_NOTE

    def test_the_sized_programs_are_the_ones_with_a_loaf_button(self):
        """Basic, French, Whole Wheat, Sweet, Super Rapid, Sandwich, GF, Cake."""
        sized = {
            p["name"] for p in westbend.PROGRAMS
            if any(c["loaf_lb"] is not None for c in p["cycles"])
        }
        assert sized == {
            "Basic", "French", "Whole Wheat", "Sweet",
            "Super Rapid", "Sandwich", "Gluten Free", "Cake",
        }

    def test_custom_records_its_adjustable_ranges(self):
        custom = next(p for p in westbend.PROGRAMS if p["name"] == "Custom")
        for span in ("3-14", "20-60", "0-24", "1-60", "0-120", "0-80"):
            assert span in custom["notes"]

    def test_bake_runs_ten_to_sixty_in_ten_minute_steps(self):
        bake = next(p for p in westbend.PROGRAMS if p["name"] == "Bake")
        assert "10-minute increments" in bake["notes"]
        assert "10 to 60" in bake["notes"]

    def test_delay_start_is_thirteen_hours_except_on_cake(self):
        for spec in westbend.PROGRAMS:
            delays = {c["delay_max_h"] for c in spec["cycles"]}
            if spec["name"] == "Cake":
                assert delays == {None}, "cake cannot be delayed"
                assert "not available" in spec["notes"]
            else:
                assert delays == {13}, spec["name"]


class TestSeedingThem:
    def test_a_run_creates_every_program_and_cycle(self, session):
        report = seeding.seed_all(session)
        session.commit()

        assert len(report.programs_added) == 12
        assert report.cycles_added == 28
        assert session.query(EquipmentProgram).count() == 12
        assert session.query(EquipmentCycle).count() == 28

    def test_the_cycles_reach_the_database_intact(self, session):
        seeding.seed_all(session)
        session.commit()

        basic = seeding.find_program(session, westbend.DEVICE, "Basic")
        three = basic.cycle_for(3.0)
        assert (three.knead1_min, three.bake_min, three.total_min) == (10, 79, 190)
        assert three.total_label == "3:10"
        assert basic.sized is True

        dough = seeding.find_program(session, westbend.DEVICE, "Dough")
        assert dough.sized is False
        assert dough.cycle_for(None).bake_min is None

    def test_the_headline_total_is_the_two_pound_one(self, session):
        seeding.seed_all(session)
        session.commit()
        basic = seeding.find_program(session, westbend.DEVICE, "Basic")
        assert basic.total_min == 180

    def test_the_menu_descriptions_are_kept(self, session):
        seeding.seed_all(session)
        session.commit()
        french = seeding.find_program(session, westbend.DEVICE, "French")
        assert "Italian" in french.notes


class TestTheEquipmentPage:
    def test_it_shows_the_cycle_times(self, client, session):
        seeding.seed_all(session)
        session.commit()

        page = client.get("/equipment").text
        assert "Cycle times" in page
        assert "Menu 1" in page
        assert "3:10" in page, "the 3 lb Basic total"
