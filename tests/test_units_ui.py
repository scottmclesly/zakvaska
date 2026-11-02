"""The unit switch, and the pages reading in whichever unit is chosen."""

from __future__ import annotations

from app.models.enums import IngredientRole, JarOrigin, RecipeCategory
from app.services import jars as jar_service
from app.services import measures
from app.services import recipes as recipe_service
from app.services import settings_store
from app.services.recipes import IngredientSpec, StageSpec


def seed_jar_with_a_feeding(session):
    jar = jar_service.create_jar(
        session, name="Homemade rye", origin=JarOrigin.HOMEMADE,
        flour_type="whole rye",
    )
    session.commit()
    jar_service.log_feeding(
        session, jar, starter_g=40, flour_g=80, water_g=80
    )
    session.commit()
    return jar


def seed_recipe(session):
    recipe = recipe_service.create_recipe(
        session, name="Borodinsky", category=RecipeCategory.RYE,
        ingredients=[
            IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
            IngredientSpec("Water", IngredientRole.WATER, 80.0),
            IngredientSpec("Salt", IngredientRole.SALT, 2.0),
        ],
        stages=[StageSpec("bake", duration_min=60)],
    )
    session.commit()
    return recipe


class TestTheSwitch:
    def test_grams_to_start_with(self, client, session):
        assert settings_store.weight_unit(session) == measures.METRIC
        assert "grams" in client.get("/").text

    def test_it_appears_on_every_page(self, client, session):
        seed_recipe(session)
        for path in ("/", "/recipes", "/bakes", "/equipment", "/backup"):
            assert "/settings/weight-unit" in client.get(path).text, path

    def test_cycling_steps_through_all_three(self, client, session):
        seen = []
        for _ in range(4):
            client.post("/settings/weight-unit", data={"next": "/"})
            session.expire_all()
            seen.append(settings_store.weight_unit(session))

        assert seen == [
            measures.US_VOLUME, measures.US_WEIGHT, measures.METRIC,
            measures.US_VOLUME,
        ]

    def test_it_comes_back_to_the_page_you_were_on(self, client, session):
        seed_recipe(session)

        response = client.post(
            "/settings/weight-unit",
            data={"next": "/recipes/1/v/1?flour=500"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/recipes/1/v/1?flour=500"

    def test_a_unit_can_be_asked_for_directly(self, client, session):
        client.post(
            "/settings/weight-unit",
            data={"next": "/", "unit": measures.US_WEIGHT},
        )
        session.expire_all()

        assert settings_store.weight_unit(session) == measures.US_WEIGHT

    def test_a_nonsense_unit_just_cycles(self, client, session):
        client.post("/settings/weight-unit", data={"next": "/", "unit": "furlongs"})
        session.expire_all()

        assert settings_store.weight_unit(session) == measures.US_VOLUME

    def test_the_setting_survives_the_next_request(self, client, session):
        client.post("/settings/weight-unit", data={"next": "/", "unit": "us_weight"})

        assert "oz / lb" in client.get("/").text

    def test_the_temperature_switch_toggles(self, client, session):
        client.post("/settings/temp-unit", data={"next": "/"})
        session.expire_all()
        assert settings_store.temp_unit(session) == "C"

        client.post("/settings/temp-unit", data={"next": "/"})
        session.expire_all()
        assert settings_store.temp_unit(session) == "F"


class TestItOnlyRedirectsInsideTheApp:
    """`next` comes from a form field, so it is not to be trusted."""

    def test_an_absolute_url_is_refused(self, client):
        response = client.post(
            "/settings/weight-unit",
            data={"next": "https://example.com/phish"},
            follow_redirects=False,
        )

        assert response.headers["location"] == "/"

    def test_a_protocol_relative_url_is_refused(self, client):
        response = client.post(
            "/settings/weight-unit",
            data={"next": "//example.com/phish"},
            follow_redirects=False,
        )

        assert response.headers["location"] == "/"

    def test_a_bare_path_is_fine(self, client):
        response = client.post(
            "/settings/weight-unit",
            data={"next": "/bakes"},
            follow_redirects=False,
        )

        assert response.headers["location"] == "/bakes"


class TestThePagesFollow:
    def test_a_feeding_reads_in_cups(self, client, session):
        jar = seed_jar_with_a_feeding(session)
        client.post("/settings/weight-unit", data={"next": "/", "unit": "us_volume"})

        body = client.get(f"/jars/{jar.id}").text

        assert "40 g" not in body
        # 40 g of starter, 80 g of rye, 80 g of water.
        assert "2 ⅔ tbsp" in body
        assert "¾ cup" in body
        assert "⅓ cup" in body

    def test_a_feeding_reads_in_ounces(self, client, session):
        jar = seed_jar_with_a_feeding(session)
        client.post("/settings/weight-unit", data={"next": "/", "unit": "us_weight"})

        body = client.get(f"/jars/{jar.id}").text

        assert "1.4 oz" in body  # 40 g
        assert "2.8 oz" in body  # 80 g

    def test_a_scaled_recipe_reads_in_cups(self, client, session):
        recipe = seed_recipe(session)
        client.post("/settings/weight-unit", data={"next": "/", "unit": "us_volume"})

        body = client.get(f"/recipes/{recipe.id}/v/1?flour=500").text

        assert "4 ⅞ cups" in body  # 500 g rye flour
        assert "Cups" in body  # the column header follows too

    def test_a_total_stays_a_weight_even_in_cups(self, client, session):
        recipe = seed_recipe(session)
        client.post("/settings/weight-unit", data={"next": "/", "unit": "us_volume"})

        body = client.get(f"/recipes/{recipe.id}/v/1?flour=500").text

        # Total dough is 910 g, which is pounds, never cups.
        assert "2 lb" in body

    def test_grams_are_what_you_get_without_touching_anything(
        self, client, session
    ):
        jar = seed_jar_with_a_feeding(session)

        body = client.get(f"/jars/{jar.id}").text

        assert "40 g starter" in body
        assert "80 g flour" in body
        assert "cup flour" not in body
