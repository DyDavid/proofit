# tests/test_jobs_fetch_url.py
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

SECRET = "https://internal.example/v1?key=AIzaSy-SECRET"


def test_non_http_url_returns_the_documented_error_envelope() -> None:
    res = client.post("/api/jobs/fetch-url", json={"url": "ftp://example.com/job"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "JOB_FETCH_FAILED"


def test_fetch_failure_does_not_echo_the_underlying_error() -> None:
    with patch("engine.ingest.scraper.scrape_job_url", side_effect=RuntimeError(SECRET)):
        res = client.post("/api/jobs/fetch-url", json={"url": "https://example.com/job"})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "JOB_FETCH_FAILED"
    assert "AIza" not in res.text and "internal.example" not in res.text


def test_refused_url_maps_to_job_url_blocked() -> None:
    with patch("engine.ingest.scraper.scrape_job_url", side_effect=ValueError("nope")):
        res = client.post("/api/jobs/fetch-url", json={"url": "https://example.com/job"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_URL_BLOCKED"
