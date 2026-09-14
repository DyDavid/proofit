from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import ApiError, install_error_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise ApiError(status_code=418, code="TEAPOT", message="dev-only message")

    return app


def test_api_error_envelope_shape() -> None:
    client = TestClient(_make_app())
    res = client.get("/boom")
    assert res.status_code == 418
    body = res.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "TEAPOT"
    assert "error_id" in body["error"]
    assert body["error"]["error_id"].startswith("err_")


def test_api_error_ids_are_unique_per_occurrence() -> None:
    client = TestClient(_make_app())
    first = client.get("/boom").json()["error"]["error_id"]
    second = client.get("/boom").json()["error"]["error_id"]
    assert first != second
