"""Picking the display units on the settings page.

The section used to be two bare forms with an `onchange="this.form.submit()"`
on one of them and a button wrapped in a <label> on the other — so it missed
`.form` entirely and rendered as unstyled native controls beside the styled
ones in every other section. It is now one form built like the rest of the
page, posting to one route.

The header's two buttons are a different thing and stay as they were: they
step through the units a tap at a time, which is what you want mid-task.
"""

from __future__ import annotations

from app.services import measures, settings_store


def _release(session):
    session.rollback()
    session.expire_all()


def _units_section(page: str) -> str:
    return page.split('<h2 class="section-title">Units</h2>')[1].split(
        "</section>"
    )[0]


# --- It is built like the rest of the page ------------------------------


class TestItMatchesThePage:
    def test_the_section_uses_the_page_s_form_class(self, client):
        """Without it, none of `.form`'s input styling applies."""
        section = _units_section(client.get("/settings").text)

        assert '<form class="form"' in section

    def test_both_controls_are_labelled_selects_in_one_field_row(self, client):
        section = _units_section(client.get("/settings").text)

        assert 'class="field-row"' in section
        assert section.count("<select") == 2
        assert section.count("<span>") == 2

    def test_it_saves_with_a_button_like_every_other_section(self, client):
        section = _units_section(client.get("/settings").text)

        assert 'class="row-actions"' in section
        assert 'class="btn" type="submit"' in section

    def test_it_carries_no_inline_javascript(self, client):
        """Behaviour lives in app.js, and this form needs none at all."""
        section = _units_section(client.get("/settings").text)

        assert "onchange" not in section
        assert "noscript" not in section

    def test_it_does_not_wrap_a_button_in_a_label(self, client):
        """A label labels a form control; a button is not one."""
        section = _units_section(client.get("/settings").text)
        labels = section.split("<label>")[1:]

        assert labels
        for label in labels:
            assert "<button" not in label.split("</label>")[0]


# --- It still sets the units --------------------------------------------


class TestItSetsTheUnits:
    def test_it_saves_both_at_once(self, client, session):
        response = client.post(
            "/settings/units",
            data={"weight_unit": measures.US_WEIGHT, "temp_unit": "C"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        _release(session)
        assert settings_store.weight_unit(session) == measures.US_WEIGHT
        assert settings_store.temp_unit(session) == "C"

    def test_the_current_units_come_back_selected(self, client, session):
        client.post(
            "/settings/units",
            data={"weight_unit": measures.US_VOLUME, "temp_unit": "C"},
        )
        _release(session)

        section = _units_section(client.get("/settings").text)

        weights = section.split('name="weight_unit"')[1].split("</select>")[0]
        temps = section.split('name="temp_unit"')[1].split("</select>")[0]
        assert f'value="{measures.US_VOLUME}" selected' in weights
        assert 'value="C" selected' in temps

    def test_every_weight_unit_is_offered(self, client):
        section = _units_section(client.get("/settings").text)
        weights = section.split('name="weight_unit"')[1].split("</select>")[0]

        for unit in measures.UNIT_CYCLE:
            assert f'value="{unit}"' in weights

    def test_both_temperatures_are_offered(self, client):
        section = _units_section(client.get("/settings").text)
        temps = section.split('name="temp_unit"')[1].split("</select>")[0]

        assert 'value="F"' in temps
        assert 'value="C"' in temps

    def test_a_unit_it_does_not_know_is_refused(self, client, session):
        response = client.post(
            "/settings/units",
            data={"weight_unit": "furlongs", "temp_unit": "F"},
        )

        assert response.status_code == 400
        _release(session)
        assert settings_store.weight_unit(session) == measures.METRIC

    def test_a_temperature_it_does_not_know_is_refused(self, client, session):
        response = client.post(
            "/settings/units",
            data={"weight_unit": measures.METRIC, "temp_unit": "K"},
        )

        assert response.status_code == 400
        _release(session)
        assert settings_store.temp_unit(session) == "F"

    def test_a_refusal_changes_nothing_at_all(self, client, session):
        """Not even the half of it that was valid."""
        response = client.post(
            "/settings/units",
            data={"weight_unit": measures.US_WEIGHT, "temp_unit": "K"},
        )

        assert response.status_code == 400
        _release(session)
        assert settings_store.weight_unit(session) == measures.METRIC


# --- The header is untouched --------------------------------------------


class TestTheHeaderSwitchStillWorks:
    def test_the_step_through_buttons_are_still_there(self, client):
        page = client.get("/settings").text

        assert "/settings/weight-unit" in page
        assert "/settings/temp-unit" in page

    def test_they_still_cycle(self, client, session):
        client.post("/settings/weight-unit", data={"next": "/"})
        _release(session)

        assert settings_store.weight_unit(session) != measures.METRIC

    def test_the_settings_form_and_the_header_set_the_same_thing(
        self, client, session
    ):
        client.post(
            "/settings/units",
            data={"weight_unit": measures.US_VOLUME, "temp_unit": "F"},
        )
        _release(session)
        assert settings_store.weight_unit(session) == measures.US_VOLUME

        client.post("/settings/weight-unit", data={"next": "/"})
        _release(session)

        assert settings_store.weight_unit(session) == measures.next_unit(
            measures.US_VOLUME
        )
