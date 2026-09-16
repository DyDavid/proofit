from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.store import AnalysisRecord, store
from engine.normalize.schema import Evidence, Job, Match, MatchResult, Requirement, Resume
from engine.rewrite import prompts
from engine.rewrite.models import ValidationResult

client = TestClient(app)


def _dispatch_call_structured(
    *, detect_response: dict[str, Any], generate_response: dict[str, Any]
) -> Callable[..., dict[str, Any]]:
    """`engine.rewrite.detect` and `engine.rewrite.generate` both do `from
    engine.rewrite import llm`, so `detect.llm` and `generate.llm` are the
    exact same module object: patching `call_structured` through either
    dotted path patches the identical attribute on that one shared module.
    Two separate `patch(...)` calls with distinct static `return_value`s
    would leave only the later-entered one live for the whole `with` block
    — the earlier one's canned response would never actually be seen by its
    call site. Handing both patches this same `tool_name`-dispatching
    `side_effect` sidesteps that: whichever patch ends up "live" still
    answers correctly for both call sites."""

    def _side_effect(*, tool_name: str, **_kwargs: object) -> dict[str, Any]:
        if tool_name == prompts.DETECT_TOOL_NAME:
            return detect_response
        if tool_name == prompts.GENERATE_TOOL_NAME:
            return generate_response
        raise AssertionError(f"unexpected tool_name in test stub: {tool_name}")

    return _side_effect


def _seed_done_analysis(analysis_id: str) -> str:
    job = Job(
        source_type="pasted",
        content_hash="deadbeef",
        title="Junior Developer",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required"),
        ],
    )
    resume = Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a dashboard for a university course project.",
                evidence_type="project",
                skills=["React"],
            ),
        ],
    )
    match = Match(
        coverage_score=50.0,
        coverage_required_only=50.0,
        realism_verdict="stretch",
        results=[
            MatchResult(
                requirement_id="r1", verdict="partial", evidence_ids=["e1"],
                reasoning="close", confidence=0.6,
            ),
        ],
        job=job,
        resume=resume,
    )
    record = AnalysisRecord(id=analysis_id, resume_id="res_test", job_id="job_test", country="cambodia")
    record.status = "done"
    record.match = match
    store.analyses[record.id] = record
    return record.id


def test_rewrites_endpoint_accepts_a_valid_candidate() -> None:
    analysis_id = _seed_done_analysis("an_test_rewrites_ok")

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 0
    assert len(body["hidden_strengths"]) == 1
    assert body["hidden_strengths"][0]["evidence_id"] == "e1"

    get_res = client.get(f"/api/analyses/{analysis_id}").json()
    assert len(get_res["match"]["hidden_strengths"]) == 1


def test_rewrites_endpoint_logs_a_rejection_after_two_failed_attempts() -> None:
    analysis_id = _seed_done_analysis("an_test_rewrites_reject")

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Worked professionally as a software engineer.",
            "facts_used": ["e1"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(
                ok=False,
                violations=[{"claim": "software engineer", "reason": "evidence is a project"}],
            ),
        ),
    ):
        before = len(store.rewrite_rejections)
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 1
    assert body["hidden_strengths"] == []
    logged = store.rewrite_rejections[before:]
    assert len(logged) == 2
    assert all(r.retry_succeeded is False for r in logged)


def test_rewrites_endpoint_flips_retry_succeeded_when_the_retry_passes() -> None:
    """Not one of the brief's four given tests, but a targeted addition: the
    endpoint's retry loop logs every failed attempt and is supposed to flip
    the *first* failure's `retry_succeeded` to `True` once a later attempt in
    the same candidate's retry loop passes validation. None of the other
    tests here exercise the "fails once, then passes" path, so this checks
    that mutation actually lands on the logged record rather than being lost."""
    analysis_id = _seed_done_analysis("an_test_rewrites_retry_flip")

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            side_effect=[
                ValidationResult(
                    ok=False,
                    violations=[{"claim": "dashboard", "reason": "borderline on the first pass"}],
                ),
                ValidationResult(ok=True, violations=[]),
            ],
        ),
    ):
        before = len(store.rewrite_rejections)
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 0
    assert len(body["hidden_strengths"]) == 1

    logged = store.rewrite_rejections[before:]
    assert len(logged) == 1
    assert logged[0].retry_succeeded is True


def test_rewrites_endpoint_requires_a_done_analysis() -> None:
    record = AnalysisRecord(id="an_test_not_ready", resume_id="res_x", job_id="job_x", country="cambodia")
    store.analyses[record.id] = record  # status defaults to "queued"

    res = client.post(f"/api/analyses/{record.id}/rewrites")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_READY"


def test_rewrites_endpoint_404s_for_an_unknown_analysis() -> None:
    res = client.post("/api/analyses/an_doesnotexist/rewrites")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
