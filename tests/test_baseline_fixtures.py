# tests/test_baseline_fixtures.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.normalize.schema import BaselineMatch, Match

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"
FIXTURE_NAMES = ["fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_fixture_validates_against_schema(name: str) -> None:
    raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    baseline = BaselineMatch.model_validate(raw)
    assert baseline.method == "tfidf"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_requirement_ids_match_the_paired_fixture(name: str) -> None:
    match_raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    baseline_raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    match = Match.model_validate(match_raw)
    baseline = BaselineMatch.model_validate(baseline_raw)
    assert match.job is not None
    requirement_ids = {r.id for r in match.job.requirements}
    baseline_ids = {r.requirement_id for r in baseline.results}
    assert requirement_ids == baseline_ids


def test_strong_fit_baseline_shows_a_credible_win_for_the_real_engine() -> None:
    """The flagship comparison: on a strong-fit posting, the real engine's
    inference-based matching clearly outperforms naive keyword overlap."""
    match_raw = json.loads((FIXTURES_DIR / "fresh_grad_strong_fit.json").read_text())
    baseline_raw = json.loads((FIXTURES_DIR / "fresh_grad_strong_fit.baseline.json").read_text())
    match = Match.model_validate(match_raw)
    baseline = BaselineMatch.model_validate(baseline_raw)
    gap = match.coverage_score - baseline.coverage_score
    assert 10 <= gap <= 35, f"strong_fit: gap was {gap}, expected a credible 10-35 point win for the real engine"


def test_stretch_and_unrealistic_show_naive_matching_closing_or_inverting_the_gap() -> None:
    """A genuine, documented finding, not a defect: on postings that ask for
    depth (years of *professional* experience, CI/CD, expert-level skill), a
    naive keyword matcher gives partial credit for surface vocabulary overlap
    (e.g. "React" appearing in an unrelated class project) that the real
    engine correctly refuses. This is the product's own argument for why
    requirement-level, evidence-based matching matters: a naive matcher
    doesn't just lose by less on these two postings — it ties or actively
    overscores an unrealistic fit, which is worse than losing outright: it's
    false confidence for the candidate.
    """
    cases = [("fresh_grad_stretch", lambda gap: gap < 10), ("unrealistic", lambda gap: gap <= 0)]
    for name, expect_pattern in cases:
        match_raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
        baseline_raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
        match = Match.model_validate(match_raw)
        baseline = BaselineMatch.model_validate(baseline_raw)
        gap = match.coverage_score - baseline.coverage_score
        assert expect_pattern(gap), f"{name}: gap was {gap}, expected the naive-matcher-overrates pattern"
