from __future__ import annotations

import io

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_resume_bad_type_uses_the_envelope() -> None:
    res = client.post(
        "/api/resumes",
        files={"file": ("resume.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "RESUME_BAD_TYPE"


def test_resume_too_large_uses_the_envelope() -> None:
    big = io.BytesIO(b"0" * (6 * 1024 * 1024))
    res = client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", big, "application/pdf")},
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "RESUME_TOO_LARGE"


def test_job_empty_on_blank_text() -> None:
    res = client.post("/api/jobs", json={"text": "   "})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_job_empty_when_neither_text_nor_url_given() -> None:
    res = client.post("/api/jobs", json={})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_job_empty_when_both_text_and_url_given() -> None:
    res = client.post("/api/jobs", json={"text": "x" * 41, "url": "https://example.com"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "JOB_EMPTY"


def test_analysis_not_found_uses_the_envelope() -> None:
    res = client.get("/api/analyses/an_doesnotexist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
