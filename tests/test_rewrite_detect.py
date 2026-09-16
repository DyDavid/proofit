from __future__ import annotations

from unittest.mock import patch

from engine.normalize.schema import Evidence, Job, Match, MatchResult, Requirement, Resume
from engine.rewrite.detect import detect_hidden_strengths


def _job() -> Job:
    return Job(
        source_type="pasted",
        content_hash="abcd1234",
        title="Junior Developer",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(id="r1", text="Experience with Python", category="hard_skill", priority="required"),
            Requirement(id="r2", text="Team leadership", category="soft_skill", priority="preferred"),
        ],
    )


def _resume() -> Resume:
    return Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a Python scraper for a class project.",
                evidence_type="project",
                skills=["Python"],
            ),
            Evidence(id="e2", source_line="Volunteered at a coding club.", evidence_type="volunteer"),
        ],
    )


def _match(job: Job) -> Match:
    return Match(
        coverage_score=50.0,
        coverage_required_only=50.0,
        realism_verdict="stretch",
        results=[
            MatchResult(
                requirement_id="r1", verdict="partial", evidence_ids=["e1"],
                reasoning="close", confidence=0.5,
            ),
            MatchResult(
                requirement_id="r2", verdict="missing",
                missing_reason="no leadership evidence", reasoning="none found", confidence=0.9,
            ),
        ],
        job=job,
    )


def test_detect_returns_a_candidate_when_the_llm_finds_one() -> None:
    match = _match(_job())
    resume = _resume()

    with patch(
        "engine.rewrite.detect.llm.call_structured",
        side_effect=[
            {"found": True, "evidence_id": "e1", "rationale": "Python scraper demonstrates the skill."},
            {"found": False},
        ],
    ):
        candidates = detect_hidden_strengths(match, resume)

    assert len(candidates) == 1
    assert candidates[0].requirement_id == "r1"
    assert candidates[0].evidence_id == "e1"


def test_detect_drops_a_candidate_citing_an_unknown_evidence_id() -> None:
    match = _match(_job())
    resume = _resume()

    with patch(
        "engine.rewrite.detect.llm.call_structured",
        side_effect=[
            {"found": True, "evidence_id": "e99", "rationale": "hallucinated id"},
            {"found": False},
        ],
    ):
        candidates = detect_hidden_strengths(match, resume)

    assert candidates == []


def test_detect_returns_nothing_for_a_match_with_no_job() -> None:
    resume = _resume()
    bare_match = Match(coverage_score=0, coverage_required_only=0, realism_verdict="stretch", results=[])
    assert detect_hidden_strengths(bare_match, resume) == []
