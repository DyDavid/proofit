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


def test_generate_quantified_priority_actions_categories():
    """Verify actionable recommendation generation across 4 categories."""
    from engine.match.rules import generate_quantified_priority_actions

    job = Job(
        source_type="pasted",
        content_hash="test-hash-accounting-123",
        title="Junior Accountant",
        industry="Accounting",
        seniority="entry",
        requirements=[
            Requirement(
                id="r1",
                text="0-1 year of experience in accounting or bookkeeping",
                category="experience",
                priority="required",
            ),
            Requirement(
                id="r2",
                text="Basic knowledge of computerized accounting systems (e.g., QuickBooks)",
                category="hard_skill",
                normalized_skill="QuickBooks",
                priority="required",
            ),
            Requirement(
                id="r3",
                text="High attention to detail",
                category="soft_skill",
                priority="required",
            ),
            Requirement(
                id="r4",
                text="Interest in learning local taxation",
                category="other",
                priority="preferred",
            ),
            Requirement(
                id="r5",
                text="Internship experience is a plus",
                category="experience",
                priority="preferred",
            ),
        ],
    )

    results = [
        MatchResult(requirement_id="r1", verdict="missing", evidence_ids=[], reasoning="No exp", missing_reason="No exp", confidence=0.9),
        MatchResult(requirement_id="r2", verdict="missing", evidence_ids=[], reasoning="No QB", missing_reason="No QB", confidence=0.9),
        MatchResult(requirement_id="r3", verdict="partial", evidence_ids=["e1"], reasoning="Some detail", confidence=0.8),
        MatchResult(requirement_id="r4", verdict="missing", evidence_ids=[], reasoning="No tax", missing_reason="No tax", confidence=0.9),
        MatchResult(requirement_id="r5", verdict="missing", evidence_ids=[], reasoning="No intern", missing_reason="No intern", confidence=0.9),
    ]

    actions = generate_quantified_priority_actions(results, job)
    assert len(actions) == 5

    # Check that generic prohibited templates are not used
    for action in actions:
        assert "Build a project or portfolio piece" not in action
        assert "specific technical outcomes" not in action
        assert "Match Boost:" in action

    # 1. Experience check
    r1_action = next(a for a in actions if "accounting or bookkeeping" in a)
    assert "Add previous internship" in r1_action or "volunteer" in r1_action

    # 2. Tools check
    r2_action = next(a for a in actions if "QuickBooks" in a)
    assert "List specific QuickBooks tasks performed" in r2_action or "certification" in r2_action

    # 3. Soft skill check
    r3_action = next(a for a in actions if "detail" in a or "Quantify" in a)
    assert "Quantify" in r3_action and ("0% error rate" in r3_action or "quality control" in r3_action)

    # 4. Domain knowledge check
    r4_action = next(a for a in actions if "tax" in a.lower())
    assert "Mention specific coursework" in r4_action or "VAT" in r4_action
