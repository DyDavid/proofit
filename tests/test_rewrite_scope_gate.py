"""Deterministic scope-inflation gate (PROJECT_SPEC.md §9 rule 2), the third
and first-run layer of `engine.rewrite.validate.validate_rewrite`
(PERSON_B_PLAN_v2.md §5 Phase 4 hardening, task 1).

`precheck_scope_inflation` fires only when *every* evidence record a rewrite
cites in `facts_used` is non-employment (`coursework`, `project`,
`competition`, `volunteer`) and the rewrite's `suggested_phrasing` contains a
forbidden phrase from `engine/rewrite/forbidden.json` — restating a class
project or unpaid work as paid professional experience. If even one cited
record is `employment`, `internship` or `part_time`, the gate must stay
silent: professional language may be legitimately supported by that record,
and that judgement belongs to the LLM layer, not this deterministic one.

Matching is case-insensitive on a leading word boundary only — `\\bphrase` —
so "professionally" matches the "professional" entry but "professor" does
not (no trailing boundary is required, only a leading one).

The LLM is never called from this suite: every case that reaches
`validate_rewrite` mocks `_call_llm_validator`, exactly as
`tests/test_rewrite_validator.py` does, so this file needs no
`ANTHROPIC_API_KEY`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.normalize.schema import Evidence
from engine.rewrite.models import Rewrite, ValidationResult
from engine.rewrite.validate import precheck_scope_inflation, validate_rewrite


def _evidence(**overrides: object) -> Evidence:
    base: dict[str, object] = dict(
        id="e1",
        source_line=(
            "Built a Python-based encryption tool for a university course project, "
            "coordinating with 2 teammates over 3 months."
        ),
        evidence_type="project",
        skills=["Python"],
        duration_months=3,
        team_size=2,
    )
    base.update(overrides)
    return Evidence(**base)


def _rewrite(suggested_phrasing: str, facts_used: list[str] | None = None) -> Rewrite:
    return Rewrite(
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing=suggested_phrasing,
        facts_used=facts_used or ["e1"],
    )


# ── Fires: project-only evidence + a forbidden phrase ───────────────────────


def test_fires_on_a_project_only_rewrite_containing_professional() -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite("Worked professionally on a Python-based encryption tool.")

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is not None
    assert result.ok is False
    assert any("professional" in v.claim for v in result.violations)


@pytest.mark.parametrize(
    "phrase",
    [
        "professional",
        "employed",
        "worked at",
        "years of experience",
        "engineer at",
    ],
)
def test_fires_for_each_forbidden_phrase(phrase: str) -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite(f"Was {phrase} the university project team.")

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is not None
    assert result.ok is False
    assert any(v.claim == phrase for v in result.violations)


# ── Does not fire: any cited record is employment/internship/part_time ──────


def test_does_not_fire_when_a_cited_record_is_employment() -> None:
    evidence = [_evidence(id="e1", evidence_type="employment")]
    rewrite = _rewrite("Worked professionally as a software engineer.", facts_used=["e1"])

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


def test_does_not_fire_when_one_of_several_cited_records_is_employment() -> None:
    evidence = [
        _evidence(id="e1", evidence_type="project"),
        _evidence(id="e2", evidence_type="employment", source_line="Part-time tutoring role."),
    ]
    rewrite = _rewrite(
        "Worked professionally on the encryption tool and tutored part-time.",
        facts_used=["e1", "e2"],
    )

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


def test_does_not_fire_when_cited_record_is_internship() -> None:
    evidence = [_evidence(id="e1", evidence_type="internship")]
    rewrite = _rewrite("Worked professionally as an intern engineer.", facts_used=["e1"])

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


def test_does_not_fire_when_cited_record_is_part_time() -> None:
    evidence = [_evidence(id="e1", evidence_type="part_time")]
    rewrite = _rewrite("Worked professionally as a part-time developer.", facts_used=["e1"])

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


# ── Does not fire: substring only, not a real word-boundary match ───────────


def test_does_not_fire_on_a_substring_professor() -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite("Worked with a professor to build the encryption tool.")

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


# ── Does not fire: clean rewrite, no forbidden phrase at all ────────────────


def test_does_not_fire_on_a_clean_rewrite() -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite("Built a Python-based encryption tool for a university course project.")

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None


# ── Return contract: None, not a passing ValidationResult ───────────────────


def test_returns_none_not_a_passing_validation_result_on_success() -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite("Built a Python-based encryption tool for a university course project.")

    result = precheck_scope_inflation(rewrite, evidence)

    assert result is None
    assert result != ValidationResult(ok=True, violations=[])


# ── validate_rewrite short-circuits: LLM never reached when the gate fires ──


def test_validate_rewrite_never_reaches_the_llm_when_the_gate_fires() -> None:
    evidence = [_evidence(evidence_type="project")]
    rewrite = _rewrite("Worked professionally on a Python-based encryption tool.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("professional" in v.claim for v in result.violations)
