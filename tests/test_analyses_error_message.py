# tests/test_analyses_error_message.py
from __future__ import annotations

import asyncio
from unittest.mock import patch

from api.routes.analyses import _run_live_analysis
from api.store import store

SECRET = "AIzaSy-SECRET-KEY at https://internal.example/v1?key=abc"


def test_live_failure_does_not_leak_the_raw_error_to_the_record() -> None:
    resume = store.add_resume(
        filename="r.pdf", content_type="application/pdf", size=1, data=b"x"
    )
    job, _ = store.add_job(raw="x" * 41, source="text")
    record = store.create_analysis(resume.id, job.id, "cambodia")

    with patch("engine.normalize.normalize_resume", side_effect=RuntimeError(SECRET)):
        asyncio.run(_run_live_analysis(record.id))

    done = store.get_analysis(record.id)
    assert done is not None
    assert done.status == "done"
    assert done.error_message
    assert SECRET not in done.error_message
    assert "AIza" not in done.error_message
