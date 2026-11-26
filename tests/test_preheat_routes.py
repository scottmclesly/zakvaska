"""The preheat on the pages: picking the method, saving the lead, drawing it.

The service tests (`test_preheat.py`) own the arithmetic. These own the parts
you can only get wrong in a template or a form: that /plan lets you say the
loaf goes in a cast-iron pot and carries that through to the bake, that the
lead time is settable and sticks, and that the band actually reaches the row
above the bake — because a preheat drawn tidily under the bake bar would
show it following the final proof, which is the misunderstanding the whole
feature exists to fix.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models.alert import Alert
from app.models.bake import Bake, BakeStageLog
from app.models.base import utcnow
from app.models.enums import AlertKind, BakeMethod, IngredientRole
from app.models.recipe import (
    EquipmentProgram,
    Recipe,
    RecipeIngredient,
    RecipeVersion,
)
from app.services import alerts as alert_service
from app.services import followalong
from app.services import ribbon as ribbon_service
from app.services import settings_store

TZ = ZoneInfo("America/New_York")


def _release(session) -> None:
    session.rollback()
    session.expire_all()


def _version(session, *, program_id: int | None = None) -> int:
    recipe = Recipe(name="Borodinsky")
    session.add(recipe)
    session.flush()
    version = RecipeVersion(
        recipe_id=recipe.id, version=1, batch_flour_g=500.0,
        default_program_id=program_id,
    )
    session.add(version)
    session.flush()
    session.add(
        RecipeIngredient(
            version_id=version.id, seq=0, name="whole rye flour",
            role=IngredientRole.FLOUR, baker_pct=100.0,
        )
    )
    session.commit()
    version_id = version.id
    _release(session)
    return version_id


def _program(session) -> int:
    program = EquipmentProgram(name="Basic", menu_no=1)
    session.add(program)
    session.commit()
    program_id = program.id
    _release(session)
    return program_id


def _start(client, session, **extra) -> str:
    version_id = extra.pop("version", None) or _version(session)
    at = (utcnow() + timedelta(minutes=30)).astimezone(TZ).strftime(
        "%Y-%m-%dT%H:%M"
    )
    data = {"version": str(version_id), "mode": "start", "at": at} | extra
    response = client.post("/plan/start", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def _bake(session, url: str) -> Bake:
    return session.get(Bake, int(url.rsplit("/", 1)[1]))


def _bake_step(session, url: str) -> BakeStageLog:
    bake_id = int(url.rsplit("/", 1)[1])
    return session.scalars(
        select(BakeStageLog).where(
            BakeStageLog.bake_id == bake_id,
            BakeStageLog.step_key == "bake",
        )
    ).one()


# --- Choosing the method ------------------------------------------------


class TestThePlanPageOffersTheMethod:
    def test_all_three_are_on_the_form(self, client, session):
        version_id = _version(session)

        page = client.get("/plan", params={"version": version_id})

        assert 'name="method"' in page.text
        for method in BakeMethod:
            assert f'value="{method.value}"' in page.text
            assert method.label in page.text

    def test_it_says_how_long_the_pot_will_want(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan", params={"version": version_id, "method": "dutch_oven"}
        )

        assert "45 minutes of preheating" in page.text
        assert "alongside the final rise" in page.text

    def test_a_plain_oven_is_told_its_own_shorter_wait(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan", params={"version": version_id, "method": "oven"}
        )

        assert "20 minutes of preheating" in page.text

    def test_the_bread_maker_has_nothing_to_preheat(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan", params={"version": version_id, "method": "bread_maker"}
        )

        assert "nothing to preheat" in page.text
        assert "minutes of preheating" not in page.text

    def test_a_recipe_with_a_program_still_opens_on_the_bread_maker(
        self, client, session
    ):
        """The inference this page has always made, now said out loud."""
        version_id = _version(session, program_id=_program(session))

        page = client.get("/plan", params={"version": version_id})

        assert 'value="bread_maker"\n                  selected' in page.text

    def test_nonsense_falls_back_rather_than_erroring(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan", params={"version": version_id, "method": "microwave"}
        )

        assert page.status_code == 200
        assert "20 minutes of preheating" in page.text


class TestStartingCarriesItThrough:
    def test_a_pot_bake_arrives_as_a_pot_bake(self, client, session):
        url = _start(client, session, method="dutch_oven", bake_temp="475")
        _release(session)

        assert _bake(session, url).method is BakeMethod.DUTCH_OVEN

    def test_and_it_carries_the_lead_time(self, client, session):
        url = _start(client, session, method="dutch_oven", bake_temp="475")
        _release(session)

        assert _bake_step(session, url).preheat_lead_min == 45

    def test_the_setting_in_force_is_the_one_written_down(
        self, client, session
    ):
        settings_store.set_setting(session, "preheat_pot_min", "60")
        session.commit()
        _release(session)

        url = _start(client, session, method="dutch_oven", bake_temp="475")
        _release(session)

        assert _bake_step(session, url).preheat_lead_min == 60

    def test_changing_the_setting_afterwards_leaves_the_bake_alone(
        self, client, session
    ):
        """A bake is a record: the lead it was planned with is part of it."""
        url = _start(client, session, method="dutch_oven", bake_temp="475")
        client.post("/settings/preheat", data={"preheat_pot_min": "30"})
        _release(session)

        assert _bake_step(session, url).preheat_lead_min == 45

    def test_an_oven_bake_gets_the_oven_lead(self, client, session):
        url = _start(client, session, method="oven", bake_temp="450")
        _release(session)

        assert _bake(session, url).method is BakeMethod.OVEN
        assert _bake_step(session, url).preheat_lead_min == 20

    def test_a_bread_maker_bake_gets_none(self, client, session):
        url = _start(client, session, method="bread_maker")
        _release(session)

        assert _bake(session, url).method is BakeMethod.BREAD_MAKER
        assert _bake_step(session, url).preheat_lead_min is None

    def test_choosing_a_program_still_means_the_machine(
        self, client, session
    ):
        """With no method said, a program decides, exactly as before."""
        program_id = _program(session)
        url = _start(client, session, program=str(program_id))
        _release(session)

        assert _bake(session, url).method is BakeMethod.BREAD_MAKER


# --- The setting --------------------------------------------------------


class TestTheSetting:
    def test_the_page_offers_both_leads(self, client):
        page = client.get("/settings")

        assert "Preheating" in page.text
        assert 'name="preheat_pot_min"' in page.text
        assert 'name="preheat_oven_min"' in page.text

    def test_the_choices_are_the_three_that_matter(self, client):
        page = client.get("/settings")

        for minutes in (30, 45, 60):
            assert f'value="{minutes}"' in page.text

    def test_it_round_trips(self, client, session):
        response = client.post(
            "/settings/preheat", data={"preheat_pot_min": "60"}
        )

        assert response.status_code == 200
        _release(session)
        assert settings_store.preheat_pot_min(session) == 60

    def test_the_oven_lead_round_trips_too(self, client, session):
        client.post("/settings/preheat", data={"preheat_oven_min": "30"})
        _release(session)

        assert settings_store.preheat_oven_min(session) == 30

    def test_a_lead_nobody_offered_is_refused(self, client, session):
        response = client.post(
            "/settings/preheat", data={"preheat_pot_min": "5"}
        )

        assert response.status_code == 400
        assert "30, 45 or 60" in response.text
        _release(session)
        assert settings_store.preheat_pot_min(session) == 45

    def test_words_instead_of_minutes_are_refused(self, client, session):
        response = client.post(
            "/settings/preheat", data={"preheat_pot_min": "an hour"}
        )

        assert response.status_code == 400
        _release(session)
        assert settings_store.preheat_pot_min(session) == 45

    def test_the_defaults_are_45_and_20(self, client, session):
        assert settings_store.preheat_pot_min(session) == 45
        assert settings_store.preheat_oven_min(session) == 20


# --- Drawing it ---------------------------------------------------------


class TestTheBand:
    def test_the_plan_draws_it(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan",
            params={
                "version": version_id, "method": "dutch_oven",
                "bake_temp": "475",
            },
        )

        assert 'class="preheat-band"' in page.text
        assert "Oven on at" in page.text
        assert 'class="ribbon-swatch is-preheat"' in page.text

    def test_a_bread_maker_plan_draws_nothing(self, client, session):
        version_id = _version(session)

        page = client.get(
            "/plan", params={"version": version_id, "method": "bread_maker"}
        )

        assert 'class="preheat-band"' not in page.text
        assert "Oven on at" not in page.text

    def test_the_running_sheet_draws_it(self, client, session):
        url = _start(client, session, method="dutch_oven", bake_temp="475")

        page = client.get(url)

        assert 'class="preheat-band"' in page.text
        assert "before the loaf goes in" in page.text

    def test_it_stays_drawn_once_the_loaf_is_in(self, client, session):
        """The band is the plan, the alert is the prompt.

        A step's bar does not vanish when the step is ticked off, and nor
        does this: the timeline is the day as it was laid out. What stops
        at that point is the heads-up, which `test_preheat.py` pins down —
        there is no use being told to preheat an oven the loaf is in.
        """
        url = _start(client, session, method="dutch_oven", bake_temp="475")
        _release(session)
        log = _bake_step(session, url)

        client.post(f"{url}/stages/{log.id}/start")
        _release(session)

        assert 'class="preheat-band"' in client.get(url).text
        assert followalong.preheat_moment(_bake_step(session, url)) is None

    def test_the_band_reaches_the_row_above_the_bake(self):
        """Over the end of the final proof, which is the point of drawing it.

        Geometry rather than a page: the band has to start where the proof
        is still running and reach up into its row, or it reads as a step
        that follows the proof — the very thing it is not.
        """
        drawn = _drawn_timeline()
        band = drawn.preheat
        baking = next(bar for bar in drawn.bars if bar.key == "bake")
        proof = next(bar for bar in drawn.bars if bar.key == "final_rise")

        assert band is not None
        # Vertically: up into the proof's row, down to the foot of the bake.
        assert band.y <= proof.y + proof.height
        assert band.y + band.height >= baking.y + baking.height
        # Horizontally: starts inside the proof and ends where the bake does.
        assert proof.x1 < band.x1 < proof.x2
        assert band.x2 == baking.x1

    def test_a_band_off_the_left_of_the_window_is_not_drawn(self):
        drawn = _drawn_timeline(window_from_bake=True)

        assert drawn.preheat is None


# --- Saying it, where it is read ----------------------------------------


class TestWhatThePageSays:
    def _fired(self, client, session, **extra):
        """A pot bake whose preheat moment has come and gone."""
        url = _start(
            client, session, method="dutch_oven", bake_temp="475", **extra
        )
        _release(session)
        log = _bake_step(session, url)
        due = log.planned_start - timedelta(
            minutes=log.preheat_lead_min
        )
        alert_service.reconcile(session, due)
        session.commit()
        _release(session)
        return url

    def test_the_banner_says_how_hot_and_how_long(self, client, session):
        self._fired(client, session)

        page = client.get("/")

        assert (
            "Preheat the oven and pot to 475°F now — bake in 45 min"
            in page.text
        )

    def test_it_follows_the_display_unit(self, client, session):
        self._fired(client, session)
        client.post("/settings/units", data={"temp_unit": "C"})

        page = client.get("/")

        assert "to 246°C now" in page.text

    def test_a_banner_with_only_the_preheat_on_it_says_so(
        self, client, session
    ):
        """"1 bake step due" would be wrong: no step is due, the oven is."""
        self._fired(client, session)
        for other in session.scalars(
            select(Alert).where(Alert.kind != AlertKind.PREHEAT_DUE)
        ):
            alert_service.acknowledge(session, other, utcnow())
        session.commit()
        _release(session)

        page = client.get("/")

        assert "oven to turn on" in page.text
        assert "bake step" not in page.text

    def test_a_banner_with_a_step_due_as_well_does_not_claim_that(
        self, client, session
    ):
        """And the other way round: a mixture is not all ovens."""
        self._fired(client, session)

        page = client.get("/")

        assert "oven to turn on" not in page.text
        assert "bake steps due" in page.text

    def test_the_notification_payload_says_the_same(self, client, session):
        url = self._fired(client, session)

        payload = client.get("/api/alerts").json()

        warm = [
            one for one in payload["alerts"] if one["kind"] == "preheat_due"
        ]
        assert len(warm) == 1
        assert warm[0]["url"] == url
        assert warm[0]["jar_id"] is None
        assert warm[0]["subject"] == (
            "Preheat the oven and pot to 475°F now — bake in 45 min"
        )

    def test_tapping_it_opens_the_bake(self, client, session):
        url = self._fired(client, session)

        page = client.get("/")

        assert f'href="{url}"' in page.text
        assert "Open the bake" in page.text

    def test_dismissing_it_takes_it_off_the_page(self, client, session):
        self._fired(client, session)
        warm = session.scalars(
            select(Alert).where(Alert.kind == AlertKind.PREHEAT_DUE)
        ).one()

        client.post(f"/alerts/{warm.id}/ack", data={"next": "/"})
        _release(session)

        assert "Preheat the oven and pot" not in client.get("/").text


def _drawn_timeline(*, window_from_bake: bool = False):
    """A timeline of two steps — a proof then a bake — with a preheat."""
    from datetime import UTC, datetime

    start = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)

    class _Spec:
        def __init__(self, key, name):
            self.key, self.name = key, name
            self.duration_min = 60.0
            self.hands_on = key == "bake"
            self.must_be_home = True
            self.conflict = None

        @property
        def clashes(self):
            return False

    class _Step(_Spec):
        def __init__(self, key, name, at, minutes):
            super().__init__(key, name)
            self.start = at
            self.end = at + timedelta(minutes=minutes)

    proof = _Step("final_rise", "Final rise in the pan", start, 120)
    baking = _Step("bake", "Bake", proof.end, 45)
    lead = 45
    warm = ribbon_service.PreheatMark(
        start=baking.start - timedelta(minutes=lead),
        end=baking.start,
        lead_min=lead,
    )
    window_start = baking.start if window_from_bake else start - timedelta(
        minutes=10
    )
    return ribbon_service.timeline(
        (proof, baking),
        start=window_start,
        end=baking.end + timedelta(minutes=10),
        now=start,
        tz=TZ,
        preheat=warm,
    )
