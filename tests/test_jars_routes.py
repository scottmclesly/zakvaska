"""The pages, end to end through HTTP.

The final class is Phase 1's acceptance check from docs/TODO-v1.md, written
out as Scott's actual setup: his homemade rye and the Soviet control.
"""

from __future__ import annotations

import re

import pytest

JAR_FIELDS = {
    "origin": "homemade",
    "state": "active",
    "feed_interval_room_h": "12",
    "feed_interval_fridge_h": "168",
}


def create_jar(client, name, **overrides) -> int:
    data = {"name": name, **JAR_FIELDS, **overrides}
    response = client.post("/jars/new", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    return int(re.fullmatch(r"/jars/(\d+)", response.headers["location"]).group(1))


class TestJarCrud:
    def test_empty_dashboard_invites_a_first_jar(self, client):
        body = client.get("/").text

        assert "No jars yet" in body
        assert "/jars/new" in body

    def test_create_then_see_it_on_the_dashboard(self, client):
        create_jar(client, "Homemade whole rye", flour_type="whole rye")

        body = client.get("/").text

        assert "Homemade whole rye" in body
        assert "No jars yet" not in body

    def test_a_jar_needs_a_name(self, client):
        response = client.post("/jars/new", data={"name": "  ", **JAR_FIELDS})

        assert response.status_code == 400
        assert "A jar needs a name." in response.text

    def test_edit_changes_the_jar(self, client):
        jar_id = create_jar(client, "Typo")

        client.post(
            f"/jars/{jar_id}/edit",
            data={"name": "Fixed", **JAR_FIELDS},
            follow_redirects=False,
        )

        assert "Fixed" in client.get(f"/jars/{jar_id}").text

    def test_missing_jar_is_a_404(self, client):
        assert client.get("/jars/999").status_code == 404

    def test_archiving_hides_it_from_the_dashboard_without_deleting(self, client):
        jar_id = create_jar(client, "Retired")

        client.post(f"/jars/{jar_id}/archive", data={"archived": "1"},
                    follow_redirects=False)
        dashboard = client.get("/").text

        assert "Archived" in dashboard  # listed under the archived heading
        assert client.get(f"/jars/{jar_id}").status_code == 200, "still reachable"

    def test_archiving_can_be_undone(self, client):
        jar_id = create_jar(client, "Back again")
        client.post(f"/jars/{jar_id}/archive", data={"archived": "1"},
                    follow_redirects=False)

        client.post(f"/jars/{jar_id}/archive", data={"archived": "0"},
                    follow_redirects=False)

        assert "Back again" in client.get("/").text


class TestStateChanges:
    def test_moving_to_the_fridge_shows_on_the_timeline(self, client):
        jar_id = create_jar(client, "Rye")

        client.post(
            f"/jars/{jar_id}/state",
            data={"state": "fridge", "note": "Two weeks away"},
            follow_redirects=False,
        )
        body = client.get(f"/jars/{jar_id}").text

        assert "Moved from active to in the fridge" in body
        assert "Two weeks away" in body

    def test_creation_is_recorded_too(self, client):
        jar_id = create_jar(client, "Rye")

        assert "Started as active" in client.get(f"/jars/{jar_id}").text


class TestFeeding:
    def test_the_form_is_prefilled_from_the_last_feeding(self, client):
        jar_id = create_jar(client, "Rye")
        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "35", "flour_g": "70", "water_g": "85"},
            follow_redirects=False,
        )

        form = client.get(f"/jars/{jar_id}/feed").text

        # One tap to repeat the last feeding, without noisy decimals.
        assert 'value="35"' in form
        assert 'value="70"' in form
        assert 'value="85"' in form

    def test_fractional_grams_survive_the_prefill(self, client):
        # Kitchen scales do tenths; trimming must not round them away.
        jar_id = create_jar(client, "Rye")
        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "12.5", "flour_g": "25", "water_g": "31.5"},
            follow_redirects=False,
        )

        form = client.get(f"/jars/{jar_id}/feed").text

        assert 'value="12.5"' in form
        assert 'value="31.5"' in form

    def test_logging_a_feeding_shows_ratio_and_hydration(self, client):
        jar_id = create_jar(client, "Rye")

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40"},
            follow_redirects=False,
        )
        body = client.get(f"/jars/{jar_id}").text

        assert "1:2:2" in body
        assert "100% hydration" in body

    def test_temperatures_round_trip_through_the_display_unit(self, client):
        jar_id = create_jar(client, "Rye")

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40",
                  "ambient_temp": "72", "water_temp": "80"},
            follow_redirects=False,
        )
        body = client.get(f"/jars/{jar_id}").text

        # Typed in °F, stored in °C, displayed in °F unchanged.
        assert "room 72°F" in body
        assert "water 80°F" in body

    @pytest.mark.parametrize("missing", ["starter_g", "flour_g", "water_g"])
    def test_grams_are_required(self, client, missing):
        jar_id = create_jar(client, "Rye")
        data = {"starter_g": "20", "flour_g": "40", "water_g": "40"}
        data[missing] = ""

        response = client.post(f"/jars/{jar_id}/feed", data=data)

        assert response.status_code == 400
        assert "is required" in response.text

    def test_a_nonsense_number_is_rejected_not_stored(self, client):
        jar_id = create_jar(client, "Rye")

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "lots", "flour_g": "40", "water_g": "40"},
        )

        assert response.status_code == 400
        assert "must be a number" in response.text

    def test_a_backdated_feeding_is_stored_at_the_time_given(self, client):
        jar_id = create_jar(client, "Rye")

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40",
                  "fed_at": "2026-03-15T08:30"},
            follow_redirects=False,
        )
        body = client.get(f"/jars/{jar_id}").text

        # Entered as local wall-clock, shown back as the same wall-clock.
        assert "08:30" in body
        assert "15 Mar" in body


class TestObservation:
    def test_logging_an_observation_shows_the_rise(self, client):
        jar_id = create_jar(client, "Rye")

        client.post(
            f"/jars/{jar_id}/observe",
            data={"start_height_mm": "20", "height_mm": "50",
                  "bubbles": "many", "smell": "sour", "texture": "webby"},
            follow_redirects=False,
        )
        body = client.get(f"/jars/{jar_id}").text

        assert "150% rise" in body
        assert "Many bubbles" in body
        assert "smells sour" in body
        assert "webby" in body

    def test_an_observation_without_heights_is_still_allowed(self, client):
        jar_id = create_jar(client, "Rye")

        response = client.post(
            f"/jars/{jar_id}/observe",
            data={"smell": "acetone"}, follow_redirects=False,
        )

        assert response.status_code == 303
        assert "smells acetone" in client.get(f"/jars/{jar_id}").text


class TestPhase1Acceptance:
    """docs/TODO-v1.md: both jars, feedings and observations, on the timeline."""

    def test_scotts_two_jars_side_by_side(self, client):
        homemade = create_jar(
            client, "Homemade whole rye",
            origin="homemade", flour_type="whole rye",
        )
        control = create_jar(
            client, "Soviet rye culture",
            origin="purchased", culture_name="Soviet rye",
            flour_type="whole rye", is_control="1",
        )

        for jar_id in (homemade, control):
            client.post(
                f"/jars/{jar_id}/feed",
                data={"starter_g": "20", "flour_g": "40", "water_g": "50",
                      "flour_type": "whole rye", "ambient_temp": "70"},
                follow_redirects=False,
            )
            client.post(
                f"/jars/{jar_id}/observe",
                data={"start_height_mm": "25", "height_mm": "45",
                      "bubbles": "vigorous", "smell": "sour"},
                follow_redirects=False,
            )

        dashboard = client.get("/").text
        assert "Homemade whole rye" in dashboard
        assert "Soviet rye culture" in dashboard
        assert "control" in dashboard

        for jar_id in (homemade, control):
            detail = client.get(f"/jars/{jar_id}").text
            assert "1:2:2.5" in detail, "derived ratio"
            assert "125% hydration" in detail, "derived hydration"
            assert "80% rise" in detail, "derived rise"
            assert "Started as active" in detail, "state history"

    def test_the_control_flag_distinguishes_the_two(self, client):
        create_jar(client, "Mine", origin="homemade")
        control = create_jar(client, "Control", origin="purchased", is_control="1")

        assert "control" in client.get(f"/jars/{control}").text


class TestErrorPagesKeepWhatYouTyped:
    """A rejected form must come back filled in, not blanked."""

    def test_the_bad_value_is_echoed_back(self, client):
        jar_id = create_jar(client, "Rye")

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "lots", "flour_g": "40", "water_g": "40"},
        )

        assert response.status_code == 400
        assert 'value="lots"' in response.text, "the typo should still be there"
        assert 'value="40"' in response.text, "and the good values kept"

    def test_a_typed_temperature_survives_a_rejected_submission(self, client):
        jar_id = create_jar(client, "Rye")

        response = client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "", "flour_g": "40", "water_g": "40",
                  "ambient_temp": "68"},
        )

        assert response.status_code == 400
        assert 'value="68"' in response.text
