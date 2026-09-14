# tests/test_analyses_baseline_and_retry.py
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.store import store

client = TestClient(app)


def _create_done_analysis() -> str:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]
    for _ in range(50):
        res = client.get(f"/api/analyses/{analysis_id}").json()
        if res["status"] == "done":
            return analysis_id
    raise AssertionError("mock analysis never finished")


def test_get_analysis_includes_a_baseline_from_the_same_fixture() -> None:
    analysis_id = _create_done_analysis()
    res = client.get(f"/api/analyses/{analysis_id}").json()
    assert res["baseline"] is not None
    assert res["baseline"]["method"] == "tfidf"
    match_requirement_ids = {r["id"] for r in res["match"]["job"]["requirements"]}
    baseline_requirement_ids = {r["requirement_id"] for r in res["baseline"]["results"]}
    assert match_requirement_ids == baseline_requirement_ids


def test_engine_failure_sets_status_failed_with_an_error_envelope() -> None:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]

    # The patch must be active for the whole POST, not just the polling that
    # follows: TestClient runs the mock background task to completion inside
    # the ASGI call for `POST /api/analyses` itself (it does not return until
    # the task — including its `asyncio.sleep`s — has finished), so patching
    # only around the later polling loop would be too late to ever be seen.
    with patch("api.store.store.pick_fixture", side_effect=RuntimeError("boom")):
        analysis_id = client.post(
            "/api/analyses",
            json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
        ).json()["analysis_id"]
        for _ in range(50):
            res = client.get(f"/api/analyses/{analysis_id}").json()
            if res["status"] == "failed":
                break
        else:
            raise AssertionError("analysis never reached failed status")

    assert res["match"] is None
    assert res["error"]["code"] == "ENGINE_FAILED"
    assert "error_id" in res["error"]


def test_retry_creates_a_new_analysis_reusing_the_same_inputs() -> None:
    resume_id = client.post(
        "/api/resumes",
        files={"file": ("r.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    job_id = client.post("/api/jobs", json={"text": "x" * 41}).json()["job_id"]
    original_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "japan"},
    ).json()["analysis_id"]

    retry_res = client.post(f"/api/analyses/{original_id}/retry")
    assert retry_res.status_code == 202
    retry_body = retry_res.json()
    assert retry_body["analysis_id"] != original_id
    assert retry_body["status"] == "queued"

    retried = store.analyses[retry_body["analysis_id"]]
    original = store.analyses[original_id]
    assert retried.resume_id == original.resume_id
    assert retried.job_id == original.job_id
    assert retried.country == original.country


def test_retry_on_unknown_id_is_analysis_not_found() -> None:
    res = client.post("/api/analyses/an_doesnotexist/retry")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
