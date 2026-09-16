"""Adversarial + legitimate cases for `engine.rewrite.validate.validate_rewrite`
(PERSON_B_PLAN_v2.md §5 Phase 3 — "Claude Code prompt — Phase 3", item 5).

Validator design, in one paragraph for the report: `validate_rewrite` runs two
independent layers in order. The first, `precheck_rewrite`, is a
deterministic, zero-cost regex pass — it extracts every number, year,
month-count and capitalized proper noun from the candidate rewrite and
rejects immediately if any of them is absent from the text of every evidence
record the rewrite cites in `facts_used`. This catches invented facts: a
fabricated year, employer, tool name or headcount. It runs first, and if it
fails, the second layer never runs at all — that is what "costs nothing"
means in practice: the loud, common failure mode is caught for free. The
second layer, `_call_llm_validator`, exists for the failure the regex
structurally cannot see: a rewrite that invents no new literal token but
still overstates the evidence semantically — a class project described as
paid employment, "participated" upgraded to "led" (PROJECT_SPEC.md §9 rule
2). Two layers, because a reviewer can point at the pre-check's exact
non-matching token for the loud failures, and at the LLM's own stated
reasoning for the quiet ones; neither layer is asked to do the other's job.

The five hallucinated cases below split 4-and-1 for exactly that reason: four
are caught by the deterministic layer alone (asserted by mocking
`_call_llm_validator` and checking it is never called), and one — the status
upgrade, which introduces no new number or proper noun — reaches and is
caught by the mocked LLM layer, demonstrating the second layer is
load-bearing rather than decorative. The LLM call itself is mocked
throughout: this suite must stay fast, free and deterministic in CI, which is
also why `engine/rewrite/llm.py`'s `_get_client()` is lazy — importing this
module and running every case below requires no `ANTHROPIC_API_KEY` at all.
"""

from __future__ import annotations

from unittest.mock import patch

from engine.normalize.schema import Evidence
from engine.rewrite.models import Rewrite, ValidationResult
from engine.rewrite.validate import validate_rewrite


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


def _rewrite(suggested_phrasing: str) -> Rewrite:
    return Rewrite(
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing=suggested_phrasing,
        facts_used=["e1"],
    )


# ── Hallucinated: caught by the deterministic pre-check, no LLM call ────────


def test_rejects_an_invented_year() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("In 2019, built a Python-based encryption tool for a course project.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("2019" in v.claim for v in result.violations)


def test_rejects_an_invented_employer() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("Built the encryption tool while working at TechNova Solutions.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("TechNova" in v.claim for v in result.violations)


def test_rejects_an_inflated_team_size() -> None:
    evidence = [_evidence(team_size=2)]
    rewrite = _rewrite("Led a team of 12 engineers building the encryption tool.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("12" in v.claim for v in result.violations)


def test_rejects_an_invented_tool() -> None:
    evidence = [_evidence(skills=["Python"])]
    rewrite = _rewrite("Built the encryption tool using Python and Kubernetes.")

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert any("Kubernetes" in v.claim for v in result.violations)


# ── Hallucinated: no new number or proper noun — only the LLM layer catches it ─


def test_rejects_a_status_upgrade_from_project_to_employment() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite(
        "Worked professionally as a software engineer, delivering production "
        "features independently."
    )
    llm_result = ValidationResult(
        ok=False,
        violations=[
            {
                "claim": "worked professionally as a software engineer",
                "reason": "Evidence is an academic course project, not paid employment.",
            }
        ],
    )

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=llm_result
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is False
    assert result.violations


# ── Legitimate rephrasings: must pass both layers ───────────────────────────


def _passing() -> ValidationResult:
    return ValidationResult(ok=True, violations=[])


def test_accepts_a_reordered_rephrasing() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite(
        "Coordinated with 2 teammates over 3 months to build a Python-based "
        "encryption tool for a university course project."
    )

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True
    assert result.violations == []


def test_accepts_a_jd_vocabulary_substitution() -> None:
    evidence = [_evidence(skills=["Python", "cryptography"])]
    rewrite = _rewrite("Implemented a Python cryptography tool for a university course project.")

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True


def test_accepts_a_condensed_rephrasing() -> None:
    evidence = [_evidence()]
    rewrite = _rewrite("Built a Python encryption tool as a university course project.")

    with patch(
        "engine.rewrite.validate._call_llm_validator", return_value=_passing()
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is True
