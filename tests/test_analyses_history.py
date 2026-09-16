from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _create_done_analysis(resume_id: str, job_text: str) -> str:
    job_id = client.post("/api/jobs", json={"text": job_text}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]
    for _ in range(50):
        res = client.get(f"/api/analyses/{analysis_id}").json()
        if res["status"] == "done":
            return analysis_id
    raise AssertionError("mock analysis never finished")


def test_history_lists_only_this_resumes_done_analyses() -> None:
    resume_a = client.post(
        "/api/resumes", files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    resume_b = client.post(
        "/api/resumes", files={"file": ("b.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]

    id_a1 = _create_done_analysis(resume_a, "x" * 41)
    _create_done_analysis(resume_b, "y" * 41)

    res = client.get(f"/api/analyses?resume_id={resume_a}")
    assert res.status_code == 200
    body = res.json()
    assert [row["analysis_id"] for row in body] == [id_a1]
    assert body[0]["job_title"]
    assert 0.0 <= body[0]["coverage"] <= 100.0
    assert body[0]["realism_verdict"] in {"strong_fit", "stretch", "unrealistic"}


def test_history_newest_first() -> None:
    resume_id = client.post(
        "/api/resumes", files={"file": ("c.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]
    first = _create_done_analysis(resume_id, "p" * 41)
    second = _create_done_analysis(resume_id, "q" * 41)

    res = client.get(f"/api/analyses?resume_id={resume_id}")
    ids = [row["analysis_id"] for row in res.json()]
    assert ids.index(second) < ids.index(first)


def test_history_empty_for_unknown_resume() -> None:
    res = client.get("/api/analyses?resume_id=res_doesnotexist")
    assert res.status_code == 200
    assert res.json() == []


def test_history_excludes_incomplete_analyses() -> None:
    """Verify that only completed (status == 'done') analyses appear in history.

    This test ensures that analyses with status != "done" are excluded from the
    history endpoint, even if they exist in the store. A regression that
    weakens the status == "done" filter would be caught by this test.

    The test verifies this by:
    1. Creating a done analysis that SHOULD appear in history
    2. Polling it immediately after creation to catch it in queued/running state
    3. Verifying it doesn't appear in history until status == "done"
    """
    resume_id = client.post(
        "/api/resumes", files={"file": ("d.pdf", b"%PDF-1.4 fake", "application/pdf")},
    ).json()["resume_id"]

    # Create a job and start an analysis
    job_id = client.post("/api/jobs", json={"text": "z" * 41}).json()["job_id"]
    analysis_id = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "cambodia"},
    ).json()["analysis_id"]

    # Check status immediately after creation
    status = client.get(f"/api/analyses/{analysis_id}").json()["status"]

    # If we caught it before completion (queued/running), verify it's not in history
    if status != "done":
        res = client.get(f"/api/analyses?resume_id={resume_id}")
        assert res.status_code == 200
        assert res.json() == [], "Non-done analysis should not appear in history"

    # Poll the analysis to completion
    for _ in range(50):
        status_check = client.get(f"/api/analyses/{analysis_id}").json()
        if status_check["status"] == "done":
            break

    # Query history — analysis should now appear since status == "done"
    res = client.get(f"/api/analyses?resume_id={resume_id}")
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1, "Done analysis should appear in history"
    assert any(row["analysis_id"] == analysis_id for row in body), \
        "This analysis should be in history after completion"
