from __future__ import annotations

from api.store import Store


def test_log_rewrite_rejection_records_every_field() -> None:
    store = Store()
    record = store.log_rewrite_rejection(
        analysis_id="an_1",
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing="Worked as a software engineer.",
        violations=[{"claim": "software engineer", "reason": "evidence is a project"}],
        retry_succeeded=False,
    )

    assert record in store.rewrite_rejections
    assert record.analysis_id == "an_1"
    assert record.retry_succeeded is False
    assert record.created_at is not None


def test_log_rewrite_rejection_accumulates_across_calls() -> None:
    store = Store()
    store.log_rewrite_rejection(
        analysis_id="an_1", requirement_id="r1", evidence_id="e1",
        suggested_phrasing="a", violations=[], retry_succeeded=True,
    )
    store.log_rewrite_rejection(
        analysis_id="an_1", requirement_id="r2", evidence_id="e2",
        suggested_phrasing="b", violations=[], retry_succeeded=False,
    )
    assert len(store.rewrite_rejections) == 2
