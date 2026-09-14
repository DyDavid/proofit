"""Golden fixtures validate against the locked schema (PERSON_B_PLAN_v2.md §5
Phase 1 task 3).

These are also the demo data used by the mock-mode API (`api/routes/`), so a
fixture that fails to parse here would break the live demo, not just a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.normalize.schema import Match

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"
FIXTURE_NAMES = [
    "fresh_grad_strong_fit",
    "fresh_grad_stretch",
    "unrealistic",
]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_validates_against_schema(name: str) -> None:
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    match = Match.model_validate(raw)
    assert match.realism_verdict in ("strong_fit", "stretch", "unrealistic")


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_has_a_verdict_for_every_requirement(name: str) -> None:
    """PROJECT_SPEC.md §9 rule 3, checked at the fixture level: every
    requirement in the job gets a verdict, even if that verdict is missing."""
    raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
    match = Match.model_validate(raw)
    assert match.job is not None
    requirement_ids = {r.id for r in match.job.requirements}
    result_ids = {r.requirement_id for r in match.results}
    assert requirement_ids == result_ids


def test_realism_verdicts_are_distinct_across_the_three_fixtures() -> None:
    """The three fixtures exist to demo three different outcomes — this fails
    loudly if two ever collapse to the same realism_verdict."""
    verdicts = []
    for name in FIXTURE_NAMES:
        raw = json.loads((FIXTURES_DIR / f"{name}.json").read_text())
        verdicts.append(Match.model_validate(raw).realism_verdict)
    assert len(set(verdicts)) == len(verdicts)
