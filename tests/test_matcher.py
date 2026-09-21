"""Unit tests for Dy David's matching engine, F4 rules, and baseline matcher."""

from __future__ import annotations

import os

from engine.match import run_baseline, run_match
from engine.match.rules import enforce_no_scope_inflation
from engine.normalize import normalize_jd, normalize_resume
from engine.normalize.schema import (
    BaselineMatch,
    Evidence,
    Job,
    Match,
    MatchResult,
    Requirement,
    Resume,
)


def test_run_match_and_baseline_mock():
    os.environ["ENGINE_MODE"] = "mock"
    job = normalize_jd("Junior Dev posting")
    resume = normalize_resume(b"Resume content", "resume.txt")

    match_result = run_match(job, resume)
    assert isinstance(match_result, Match)
    assert 0.0 <= match_result.coverage_score <= 100.0
    assert len(match_result.results) > 0

    baseline_result = run_baseline(job, resume)
    assert isinstance(baseline_result, BaselineMatch)
    assert baseline_result.method == "tfidf"
    assert 0.0 <= baseline_result.coverage_score <= 100.0


def test_enforce_no_scope_inflation():
    """Verify Rule 2: non-employment evidence downgrades 'proven' on experience req to 'partial'."""
    job = Job(
        source_type="pasted",
        content_hash="test-hash-123456",
        title="Web Dev",
        industry="Tech",
        seniority="entry",
        requirements=[
            Requirement(
                id="r1",
                text="1 year of web development experience",
                category="experience",
                priority="required",
            )
        ],
    )
    resume = Resume(
        evidence=[
            Evidence(
                id="e1",
                source_line="Built a personal blog project using HTML/CSS",
                evidence_type="project",
            )
        ]
    )
    initial_results = [
        MatchResult(
            requirement_id="r1",
            verdict="proven",
            evidence_ids=["e1"],
            reasoning="Candidate built personal blog.",
            confidence=0.8,
        )
    ]

    adjusted = enforce_no_scope_inflation(initial_results, job, resume)
    assert adjusted[0].verdict == "partial"
    assert "F4" in adjusted[0].reasoning
