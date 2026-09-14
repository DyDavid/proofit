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


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_baseline_scores_meaningfully_below_the_real_match(name: str) -> None:
    match_raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    baseline_raw = json.loads((FIXTURES_DIR / f"{name}.baseline.json").read_text())
    match = Match.model_validate(match_raw)
    baseline = BaselineMatch.model_validate(baseline_raw)
    gap = match.coverage_score - baseline.coverage_score
    assert 10 <= gap <= 35, f"{name}: gap was {gap}, expected a credible 10-35 point gap"
