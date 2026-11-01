"""Form parsing must stay available.

Phase 1 onwards is all HTML forms. Without python-multipart, FastAPI's Form()
raises at *route definition* time, so losing the dependency would stop the app
importing rather than fail one request. This guards the capability itself.
"""

from __future__ import annotations

from fastapi import FastAPI, Form, Request
from fastapi.testclient import TestClient


def _probe_app() -> FastAPI:
    app = FastAPI()

    @app.post("/declared")
    def declared(starter_g: int = Form(), notes: str = Form()):
        return {"starter_g": starter_g, "notes": notes}

    @app.post("/raw")
    async def raw(request: Request):
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}

    return app


def test_urlencoded_form_reaches_a_declared_endpoint():
    with TestClient(_probe_app()) as client:
        response = client.post(
            "/declared", data={"starter_g": "60", "notes": "smells sharp"}
        )

    assert response.status_code == 200
    # Form() coerces to the annotated type; raw form data would stay a string.
    assert response.json() == {"starter_g": 60, "notes": "smells sharp"}


def test_multipart_form_parses_too():
    # What a phone camera upload sends in Phase 5.
    with TestClient(_probe_app()) as client:
        response = client.post(
            "/raw",
            data={"caption": "crumb shot"},
            files={"photo": ("crumb.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )

    assert response.status_code == 200
    assert response.json() == {"caption": "crumb shot"}
