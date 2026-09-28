"""Tests for the Proofit FastAPI backend."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "engine_mode" in data
    assert "app_version" in data


def test_api_submit_job_text():
    sample_text = (
        "We are looking for a Junior Python Developer in Phnom Penh. "
        "Must have basic experience with FastAPI and PostgreSQL database. "
        "Strong communication skills and willingness to learn."
    )
    response = client.post("/api/jobs", json={"text": sample_text})
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["job_id"].startswith("job_")


def test_api_upload_resume():
    fake_pdf = io.BytesIO(b"%PDF-1.4 Fake PDF Content")
    response = client.post(
        "/api/resumes",
        files={"file": ("my_resume.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "resume_id" in data
    assert data["resume_id"].startswith("res_")


def test_api_create_and_get_analysis():
    # 1. Add job
    sample_text = (
        "We are looking for a Junior Python Developer in Phnom Penh. "
        "Must have basic experience with FastAPI and PostgreSQL database. "
        "Strong communication skills and willingness to learn."
    )
    job_res = client.post("/api/jobs", json={"text": sample_text})
    job_id = job_res.json()["job_id"]

    # 2. Add resume
    fake_pdf = io.BytesIO(b"%PDF-1.4 Fake PDF Content")
    res_res = client.post(
        "/api/resumes",
        files={"file": ("my_resume.pdf", fake_pdf, "application/pdf")},
    )
    resume_id = res_res.json()["resume_id"]

    # 3. Create analysis
    analysis_res = client.post(
        "/api/analyses",
        json={"job_id": job_id, "resume_id": resume_id, "country": "KH"},
    )
    assert analysis_res.status_code == 202
    analysis_id = analysis_res.json()["analysis_id"]

    # 4. Get analysis status
    get_res = client.get(f"/api/analyses/{analysis_id}")
    assert get_res.status_code == 200
    status_data = get_res.json()
    assert status_data["status"] in ("queued", "running", "done")
