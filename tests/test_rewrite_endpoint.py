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


def _seed_done_analysis(analysis_id: str, country: str = "cambodia") -> str:
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
    record = AnalysisRecord(id=analysis_id, resume_id="res_test", job_id="job_test", country=country)
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


def test_rewrites_endpoint_does_not_flip_retry_succeeded_on_a_later_integrity_failure() -> None:
    """Guards the fix that moved `first_failure.retry_succeeded = True` out of
    the retry loop's `if result.ok:` branch and to after the `HiddenStrength`
    construction actually succeeds.

    Here the first attempt fails `validate_rewrite` (logged, `first_failure`
    set), and the retry attempt *passes* `validate_rewrite` — but its
    `facts_used` omits the anchor's own evidence_id (the same trick
    `test_rewrites_endpoint_gracefully_rejects_a_facts_used_integrity_failure`
    uses), so `HiddenStrength`'s own `_cites_its_own_evidence` validator
    rejects it on construction, well after `result.ok` was already `True`.
    The first failure's logged record must still show `retry_succeeded is
    False`: the retry did not actually succeed, a second, separate rejection
    gets logged for the integrity failure, and `RewriteRejection` — "a report
    figure for the evaluation chapter" (`api/store.py`) — must not disagree
    with itself about what happened."""
    analysis_id = _seed_done_analysis("an_test_rewrites_retry_flip_then_integrity_fail")

    detect_response = {"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."}
    generate_responses = [
        # Attempt 1: cites e1, whose evidence includes the skill "React" —
        # the only checkable token here — so precheck_rewrite passes and
        # falls through to the (mocked) LLM layer, which fails it.
        {
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
        # Attempt 2 (the retry): zero checkable tokens (no numbers, no
        # non-sentence-initial capitalized words), so precheck_rewrite
        # passes no matter what facts_used says — and facts_used omits "e1",
        # the anchor's own evidence_id.
        {
            "suggested_phrasing": "Worked professionally as a software engineer, delivering "
            "production features independently.",
            "facts_used": ["e2"],
        },
    ]

    def _generate_stub(*, tool_name: str, **_kwargs: object) -> dict[str, Any]:
        if tool_name == prompts.DETECT_TOOL_NAME:
            return detect_response
        if tool_name == prompts.GENERATE_TOOL_NAME:
            return generate_responses.pop(0)
        raise AssertionError(f"unexpected tool_name in test stub: {tool_name}")

    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=_generate_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=_generate_stub),
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
    assert body["rejected_count"] == 1
    assert body["hidden_strengths"] == []

    logged = store.rewrite_rejections[before:]
    assert len(logged) == 2, "the first failure and the later integrity failure should both be logged"
    assert logged[0].retry_succeeded is False, (
        "the retry passed validate_rewrite but its HiddenStrength then failed the "
        "facts_used/evidence_id integrity check, so the first failure must not be "
        "misreported as a successful retry"
    )


def test_rewrites_endpoint_gracefully_rejects_a_facts_used_integrity_failure() -> None:
    """`validate_rewrite`'s two layers judge the rewrite's *phrasing*, not
    whether `facts_used` actually contains the anchor's own `evidence_id`.
    `precheck_rewrite` only fires on a checkable token (a number or a
    non-sentence-initial proper noun) — a phrasing with none of those (the
    same shape as test_rewrite_validator.py's
    test_rejects_a_status_upgrade_from_project_to_employment) passes the
    precheck regardless of `facts_used`. If the LLM validator layer then also
    approves it, `HiddenStrength`'s own `_cites_its_own_evidence` validator
    (engine/normalize/schema.py) is the only thing left to catch a
    `facts_used` that omits the anchor id — this must be caught and turned
    into a graceful rejection, not left to crash the endpoint with a raw,
    unenveloped 500."""
    analysis_id = _seed_done_analysis("an_test_rewrites_facts_used_integrity")

    call_structured_stub = _dispatch_call_structured(
        detect_response={"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."},
        generate_response={
            # Zero checkable tokens: no numbers, no non-sentence-initial
            # capitalized words — precheck_rewrite passes no matter what
            # facts_used says.
            "suggested_phrasing": "Worked professionally as a software engineer, delivering "
            "production features independently.",
            # Omits "e1", the anchor's own evidence_id.
            "facts_used": ["e2"],
        },
    )
    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=call_structured_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=call_structured_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            # Simulates the LLM layer approving the phrasing itself — it was
            # never asked to judge facts_used.
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        before = len(store.rewrite_rejections)
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    body = res.json()
    assert body["rejected_count"] == 1
    assert body["hidden_strengths"] == []

    get_res = client.get(f"/api/analyses/{analysis_id}").json()
    assert get_res["match"]["hidden_strengths"] == []

    logged = store.rewrite_rejections[before:]
    assert len(logged) == 1
    assert logged[0].retry_succeeded is False


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


def test_rewrites_endpoint_passes_the_destination_tone_notes_into_the_prompt() -> None:
    """Task 4 (c): `create_rewrites` resolves `record.country` through
    `rules_for` and passes `CountryRules.tone_notes` into `generate_rewrite`.
    Seeds the analysis with `country="singapore"` — a real
    `AnalyzeForm.tsx`-shaped value — and asserts one of Singapore's actual
    `tone_notes` (engine/country/rules.json) reaches the prompt the (mocked)
    model is sent, proving the wiring is live end to end rather than merely
    plumbed and unused."""
    from engine.country.rules import rules_for

    analysis_id = _seed_done_analysis("an_test_rewrites_tone_notes", country="singapore")
    singapore_tone_note = rules_for("singapore").tone_notes[0]

    captured: dict[str, str] = {}

    def _generate_stub(*, tool_name: str, user: str = "", **_kwargs: object) -> dict[str, Any]:
        if tool_name == prompts.DETECT_TOOL_NAME:
            return {"found": True, "evidence_id": "e1", "rationale": "React dashboard fits."}
        if tool_name == prompts.GENERATE_TOOL_NAME:
            captured["user"] = user
            return {
                "suggested_phrasing": "Built a React dashboard for a university course project.",
                "facts_used": ["e1"],
            }
        raise AssertionError(f"unexpected tool_name in test stub: {tool_name}")

    with (
        patch("engine.rewrite.detect.llm.call_structured", side_effect=_generate_stub),
        patch("engine.rewrite.generate.llm.call_structured", side_effect=_generate_stub),
        patch(
            "engine.rewrite.validate._call_llm_validator",
            return_value=ValidationResult(ok=True, violations=[]),
        ),
    ):
        res = client.post(f"/api/analyses/{analysis_id}/rewrites")

    assert res.status_code == 200
    assert res.json()["rejected_count"] == 0
    assert singapore_tone_note in captured["user"]


def test_rewrites_endpoint_works_when_destination_has_no_country_rules() -> None:
    """The UI's "other" destination has no `CountryRules` —
    `rules_for("other")` returns `None` by design, and `create_rewrites`
    must degrade to `tone_notes=None` rather than erroring."""
    analysis_id = _seed_done_analysis("an_test_rewrites_no_country_rules", country="other")

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
