"""Alerts through HTTP: the banner, the JSON feed, ack and snooze."""

from __future__ import annotations

from datetime import timedelta

from app.db import get_sessionmaker
from app.models.base import utcnow
from app.models.enums import JarOrigin, JarState
from app.services import alerts as alert_service
from app.services import jars as jar_service


def overdue_jar(name: str = "Soviet rye", hours_ago: int = 20) -> int:
    """A jar that is already past due, with its alert fired."""
    with get_sessionmaker()() as session:
        jar = jar_service.create_jar(
            session, name=name, origin=JarOrigin.PURCHASED,
            state=JarState.ACTIVE, feed_interval_room_h=12,
        )
        jar_service.log_feeding(
            session, jar, fed_at=utcnow() - timedelta(hours=hours_ago),
            starter_g=20, flour_g=40, water_g=40,
        )
        session.commit()
        alert_service.reconcile(session, utcnow())
        session.commit()
        return jar.id


def first_alert_id(client) -> int:
    return client.get("/api/alerts").json()["alerts"][0]["id"]


class TestBanner:
    def test_an_overdue_jar_shows_a_banner_on_the_dashboard(self, client):
        overdue_jar()

        body = client.get("/").text

        assert "needs feeding" in body
        assert "Soviet rye" in body
        assert "overdue" in body

    def test_the_banner_follows_you_onto_other_pages(self, client):
        jar_id = overdue_jar()

        # It is included by the shared renderer, so no page can forget it.
        assert "needs feeding" in client.get(f"/jars/{jar_id}").text
        assert "needs feeding" in client.get(f"/jars/{jar_id}/observe").text

    def test_no_banner_when_nothing_is_due(self, client):
        assert "needs feeding" not in client.get("/").text

    def test_the_count_is_pluralised(self, client):
        overdue_jar("One")
        overdue_jar("Two")

        body = client.get("/").text

        assert "jars need feeding" in body

    def test_notification_permission_is_only_offered_never_taken(self, client):
        overdue_jar()

        body = client.get("/").text

        # Permission must be requested from a click, not on page load.
        assert "Enable browser notifications" in body


class TestAlertsApi:
    def test_lists_what_is_showing(self, client):
        jar_id = overdue_jar()

        payload = client.get("/api/alerts").json()

        assert payload["count"] == 1
        alert = payload["alerts"][0]
        assert alert["jar_id"] == jar_id
        assert alert["jar_name"] == "Soviet rye"
        assert alert["kind"] == "feed_due"
        assert "overdue" in alert["overdue_by"]
        assert alert["url"] == f"/jars/{jar_id}/feed"

    def test_is_empty_when_nothing_is_due(self, client):
        assert client.get("/api/alerts").json() == {"count": 0, "alerts": []}

    def test_reading_it_does_not_change_anything(self, client):
        overdue_jar()

        first = client.get("/api/alerts").json()
        second = client.get("/api/alerts").json()

        # Whether a tab is open must never affect whether an alert exists.
        assert first == second


class TestAcknowledgeRoute:
    def test_dismissing_clears_the_banner(self, client):
        overdue_jar()
        alert_id = first_alert_id(client)

        client.post(f"/alerts/{alert_id}/ack", data={"next": "/"},
                    follow_redirects=False)

        assert client.get("/api/alerts").json()["count"] == 0
        assert "needs feeding" not in client.get("/").text

    def test_it_returns_you_to_where_you_were(self, client):
        jar_id = overdue_jar()
        alert_id = first_alert_id(client)

        response = client.post(
            f"/alerts/{alert_id}/ack", data={"next": f"/jars/{jar_id}"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/jars/{jar_id}"

    def test_unknown_alert_is_a_404(self, client):
        assert client.post("/alerts/999/ack", data={"next": "/"}).status_code == 404


class TestSnoozeRoute:
    def test_snoozing_hides_it(self, client):
        overdue_jar()
        alert_id = first_alert_id(client)

        client.post(f"/alerts/{alert_id}/snooze",
                    data={"minutes": "30", "next": "/"}, follow_redirects=False)

        assert client.get("/api/alerts").json()["count"] == 0

    def test_a_custom_snooze_is_accepted(self, client):
        overdue_jar()
        alert_id = first_alert_id(client)

        response = client.post(
            f"/alerts/{alert_id}/snooze", data={"minutes": "7", "next": "/"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert client.get("/api/alerts").json()["count"] == 0

    def test_a_nonsense_snooze_is_refused(self, client):
        overdue_jar()
        alert_id = first_alert_id(client)

        assert client.post(f"/alerts/{alert_id}/snooze",
                           data={"minutes": "soon"}).status_code == 400
        assert client.post(f"/alerts/{alert_id}/snooze",
                           data={"minutes": "0"}).status_code == 400

    def test_the_jar_is_still_listed_as_overdue_underneath(self, client):
        # Snoozing hides the nag, it does not pretend the jar was fed.
        jar_id = overdue_jar()
        alert_id = first_alert_id(client)

        client.post(f"/alerts/{alert_id}/snooze",
                    data={"minutes": "30", "next": "/"}, follow_redirects=False)
        body = client.get("/").text

        assert "needs feeding" not in body
        assert "overdue" in body, "the dashboard card should still say so"


class TestFeedingClearsTheAlert:
    def test_logging_a_feeding_dismisses_it(self, client):
        jar_id = overdue_jar()
        assert client.get("/api/alerts").json()["count"] == 1

        client.post(
            f"/jars/{jar_id}/feed",
            data={"starter_g": "20", "flour_g": "40", "water_g": "40"},
            follow_redirects=False,
        )

        assert client.get("/api/alerts").json()["count"] == 0
        assert "needs feeding" not in client.get("/").text
