"""The about page: what the app is, and what this install is holding."""

from __future__ import annotations

from app import __version__
from app.models.enums import IngredientRole, JarOrigin, PhotoOwner, RecipeCategory
from app.services import jars as jar_service
from app.services import photos as photo_service
from app.services import recipes as recipe_service
from app.services.recipes import IngredientSpec, StageSpec
from tests.test_photos_service import make_image


class TestThePage:
    def test_it_renders(self, client):
        response = client.get("/about")
        assert response.status_code == 200
        assert "About zakvaska" in response.text

    def test_it_says_what_the_app_is_for(self, client):
        text = client.get("/about").text
        assert "Borodinsky" in text
        assert "control" in text

    def test_it_shows_the_version(self, client):
        assert __version__ in client.get("/about").text

    def test_it_shows_the_display_time_zone(self, client):
        assert "America/New_York" in client.get("/about").text

    def test_it_shows_where_the_data_lives(self, client, data_dir):
        assert str(data_dir) in client.get("/about").text

    def test_it_tells_you_where_a_bake_starts(self, client):
        """The one thing that is not findable from the bakes page."""
        text = client.get("/about").text
        assert "Bake this" in text

    def test_it_explains_that_cups_are_approximate(self, client):
        assert "approximate" in client.get("/about").text


class TestTheCounts:
    def test_an_empty_notebook_counts_zero(self, client):
        text = client.get("/about").text
        assert "<dd>0</dd>" in text

    def test_rows_and_photos_are_counted(self, client, session):
        jar = jar_service.create_jar(
            session, name="Homemade rye", origin=JarOrigin.HOMEMADE,
            flour_type="whole rye",
        )
        session.commit()
        jar_service.log_feeding(
            session, jar, starter_g=20, flour_g=40, water_g=40
        )
        recipe_service.create_recipe(
            session, name="Borodinsky", category=RecipeCategory.RYE,
            ingredients=[
                IngredientSpec("Whole rye flour", IngredientRole.FLOUR, 100.0),
                IngredientSpec("Water", IngredientRole.WATER, 80.0),
            ],
            stages=[StageSpec("scald", duration_min=240, temp_c=65.0)],
        )
        photo_service.attach(
            session, owner_type=PhotoOwner.JAR, owner_id=jar.id,
            data=make_image(), caption="day three",
        )
        session.commit()

        text = client.get("/about").text
        # One jar, one feeding, one recipe, no bakes, one photo.
        assert "<dd>1</dd>" in text
        assert "Jars" in text and "Bakes" in text

    def test_the_schema_revision_is_reported(self, client):
        """Tests build the schema with create_all, so it is never stamped."""
        assert "not stamped" in client.get("/about").text


class TestItIsReachable:
    def test_every_page_links_to_it(self, client):
        for path in ("/", "/recipes", "/bakes", "/equipment", "/backup"):
            assert 'href="/about"' in client.get(path).text, path

    def test_it_links_on_to_backup(self, client):
        assert 'href="/backup"' in client.get("/about").text
