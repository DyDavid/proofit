"""Test for rewrites & history API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.store import store


client = TestClient(app)


def test_rewrites_and_history_api() -> None:
    # 1. Create resume
    res_resp = client.post(
        "/api/resumes",
        files={"file": ("test.pdf", b"%PDF-1.4 Kosal Vong Vue.js Node.js", "application/pdf")},
    )
    assert res_resp.status_code == 200
    resume_id = res_resp.json()["resume_id"]

    # 2. Create job
    job_resp = client.post(
        "/api/jobs",
        json={"text": "Vue.js Developer requiring Vue.js and Node.js."},
    )
    assert job_resp.status_code == 200
    job_id = job_resp.json()["job_id"]

    # 3. Create analysis
    an_resp = client.post(
        "/api/analyses",
        json={"resume_id": resume_id, "job_id": job_id, "country": "KH"},
    )
    assert an_resp.status_code == 202
    analysis_id = an_resp.json()["analysis_id"]

    # Manually populate match for immediate test execution
    record = store.analyses[analysis_id]
    record.status = "done"
    record.match = store.pick_fixture(job_id)

    # 4. Trigger rewrites
    rw_resp = client.post(f"/api/analyses/{analysis_id}/rewrites")
    assert rw_resp.status_code == 200
    data = rw_resp.json()
    assert "hidden_strengths" in data
    assert "rejections_count" in data

    # 5. Get history
    hist_resp = client.get(f"/api/analyses?resume_id={resume_id}")
    assert hist_resp.status_code == 200
    hist_list = hist_resp.json()
    assert len(hist_list) >= 1
    assert hist_list[0]["id"] == analysis_id

    # 6. Country rules API
    c_resp = client.get("/api/country/rules/SG")
    assert c_resp.status_code == 200
    c_data = c_resp.json()
    assert c_data["country_code"] == "SG"
    assert "visa_terms" in c_data
