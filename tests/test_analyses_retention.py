"""Tests for 30-day storage retention cleanup (analyses, saved resumes, jobs)."""

from __future__ import annotations

from datetime import timedelta

from api.store import RETENTION_DAYS, Store
from engine.normalize.schema import utcnow


def test_cleanup_expired_records_purges_old_analyses_and_resumes(monkeypatch) -> None:
    s = Store()
    now = utcnow()
    old_ts = now - timedelta(days=RETENTION_DAYS + 2)
    recent_ts = now - timedelta(days=5)

    # Seed an expired resume and a recent resume
    old_res = s.add_resume("old.pdf", "application/pdf", 100, user_id="u1")
    recent_res = s.add_resume("recent.pdf", "application/pdf", 100, user_id="u1")

    # Seed an expired job and a recent job
    old_job, _ = s.add_job("Old JD text", "text")
    recent_job, _ = s.add_job("Recent JD text", "text")

    # Seed an expired analysis and a recent analysis
    old_an = s.create_analysis(old_res.id, old_job.id, "KH", user_id="u1")
    old_an.status = "done"
    old_an.match = s.pick_fixture(old_job.id)

    recent_an = s.create_analysis(recent_res.id, recent_job.id, "KH", user_id="u1")
    recent_an.status = "done"
    recent_an.match = s.pick_fixture(recent_job.id)

    # Set timestamps after creation so create_analysis's initial cleanup sweep doesn't purge them prematurely
    old_res.created_at = old_ts
    recent_res.created_at = recent_ts
    old_job.created_at = old_ts
    recent_job.created_at = recent_ts
    old_an.created_at = old_ts
    recent_an.created_at = recent_ts

    counts = s.cleanup_expired_records(force=True)
    assert counts["analyses"] == 1
    assert counts["resumes"] == 1
    assert counts["jobs"] == 1

    assert old_an.id not in s.analyses
    assert recent_an.id in s.analyses
    assert old_res.id not in s.resumes
    assert recent_res.id in s.resumes
    assert old_job.id not in s.jobs
    assert recent_job.id in s.jobs


def test_analyses_for_resume_excludes_expired_records() -> None:
    s = Store()
    now = utcnow()

    res = s.add_resume("cv.pdf", "application/pdf", 100, user_id="u2")
    job, _ = s.add_job("Software Engineer", "text")

    old_an = s.create_analysis(res.id, job.id, "KH", user_id="u2")
    old_an.status = "done"
    old_an.match = s.pick_fixture(job.id)
    old_an.created_at = now - timedelta(days=RETENTION_DAYS + 1)

    fresh_an = s.create_analysis(res.id, job.id, "KH", user_id="u2")
    fresh_an.status = "done"
    fresh_an.match = s.pick_fixture(job.id)
    fresh_an.created_at = now - timedelta(days=1)

    # Even if throttled cleanup hasn't run again yet, `analyses_for_resume` filters by cutoff
    s._last_cleanup_at = now
    history = s.analyses_for_resume(user_id="u2")
    assert [a.id for a in history] == [fresh_an.id]


def test_find_and_count_user_resumes_excludes_expired() -> None:
    s = Store()
    now = utcnow()

    old_res = s.add_resume("cv.pdf", "application/pdf", 100, user_id="u3")
    old_res.created_at = now - timedelta(days=RETENTION_DAYS + 1)

    s._last_cleanup_at = now
    assert s.count_user_resumes("u3") == 0
    assert s.find_user_resume("u3", "cv.pdf") is None
