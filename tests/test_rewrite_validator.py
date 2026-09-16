"""Adversarial + legitimate cases for `engine.rewrite.validate.validate_rewrite`
(PERSON_B_PLAN_v2.md §5 Phase 3 task 4; grown to 30 labelled cases in Phase 4
hardening task 2, after task 1 added the third layer below).

Validator design, in one paragraph for the report: `validate_rewrite` runs
three layers in order, and the order is load-bearing. The first,
`precheck_scope_inflation`, is a deterministic, zero-cost wordlist gate:
PROJECT_SPEC.md §9 rule 2 ("no scope inflation") enforced as code rather than
as a prompt instruction. It fires only when *every* evidence record the
rewrite cites in `facts_used` is non-employment (`coursework`, `project`,
`competition`, `volunteer`) *and* the rewrite's phrasing contains a forbidden
phrase from `engine/rewrite/forbidden.json` (e.g. "professional", "worked
at") — if even one cited record is `employment`, `internship` or
`part_time`, professional language may be legitimately supported by that
record, so the gate stays silent and defers to the LLM layer. The second,
`precheck_rewrite`, is also a deterministic, zero-cost regex pass: it
extracts every number, year, month-count and capitalized proper noun from the
candidate rewrite and rejects immediately if any of them is absent from the
text of every evidence record the rewrite cites in `facts_used`. This catches
invented facts — a fabricated year, employer, tool name or headcount. Both
deterministic layers run first, and if either fails, the LLM layer never runs
at all — that is what "costs nothing" means in practice: the loud, common
failure modes are caught for free. The third layer, `_call_llm_validator`,
exists for the failure neither regex layer can see: a rewrite that invents no
new literal token, uses no forbidden phrase, and cites a record whose
evidence type would not by itself trip the scope gate, but still overstates
the evidence semantically — a class project's "participated" upgraded to
"led", or an invented outcome no cited record supports. Three layers, because
a reviewer can point at the scope gate's exact forbidden phrase, or the
pre-check's exact non-matching token, for the loud failures, and at the LLM's
own stated reasoning for the quiet ones; no layer is asked to do another's
job.

The 30 cases below (`tests/rewrite_cases.py`) split into 20 adversarial
across the six categories the report's precision/recall table names, plus 10
legitimate rephrasings that must pass all three layers — including three
that cite a genuine `employment`/`internship`/`part_time` record while using
professional language, proving the Task 1 gate's all-cited-are-non-employment
condition actually holds rather than over-firing on every mention of
"professional". Every case's `caught_by` label was verified by running the
deterministic layers directly, not assumed from the category name (see
`tests/rewrite_cases.py`'s module docstring for how and why that matters).

The LLM call itself is mocked throughout: this suite must stay fast, free and
deterministic in CI, which is also why `engine/rewrite/llm.py`'s
`_get_client()` is lazy — importing this module and running every case below
requires no `ANTHROPIC_API_KEY` at all.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.normalize.schema import Evidence
from engine.rewrite.models import Rewrite, ValidationResult, Violation
from engine.rewrite.validate import validate_rewrite
from tests.rewrite_cases import BASE_SOURCE_LINE, CASES, ValidatorCase

_ADVERSARIAL_CATEGORIES = {
    "magnitude_inflation",
    "duration_inflation",
    "status_upgrade",
    "tool_insertion",
    "outcome_invention",
    "subtle_paraphrase",
}


def _evidence_for(case: ValidatorCase) -> Evidence:
    base: dict[str, object] = dict(
        id="e1",
        source_line=BASE_SOURCE_LINE,
        evidence_type="project",
        skills=["Python"],
        duration_months=3,
        team_size=2,
    )
    base.update(case.evidence_overrides)
    return Evidence(**base)


def _rewrite_for(case: ValidatorCase) -> Rewrite:
    return Rewrite(
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing=case.suggested_phrasing,
        facts_used=["e1"],
    )


def _mocked_llm_result(case: ValidatorCase) -> ValidationResult:
    """What the (mocked) LLM layer returns for `case`: a rejection for
    `caught_by == "llm"` cases — standing in for the real semantic read the
    deterministic layers structurally cannot perform — and a pass for every
    other case, since those either never reach this layer (scope/precheck
    already rejected) or are legitimate and must clear it."""
    if case.caught_by == "llm":
        return ValidationResult(
            ok=False,
            violations=[
                Violation(
                    claim=case.suggested_phrasing,
                    reason=f"Mocked LLM rejection for {case.category} case {case.id!r}.",
                )
            ],
        )
    return ValidationResult(ok=True, violations=[])


# ── Every case: the end-to-end verdict matches its label ────────────────────


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_validator_dataset(case: ValidatorCase) -> None:
    evidence = [_evidence_for(case)]
    rewrite = _rewrite_for(case)

    with patch(
        "engine.rewrite.validate._call_llm_validator",
        return_value=_mocked_llm_result(case),
    ):
        result = validate_rewrite(rewrite, evidence)

    assert result.ok is not case.should_reject


# ── "Costs nothing": scope/precheck cases never reach the LLM at all ────────


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.caught_by in {"scope", "precheck"}],
    ids=lambda c: c.id,
)
def test_deterministic_layers_never_call_the_llm(case: ValidatorCase) -> None:
    evidence = [_evidence_for(case)]
    rewrite = _rewrite_for(case)

    with patch("engine.rewrite.validate._call_llm_validator") as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_not_called()
    assert result.ok is False
    assert result.violations


# ── The LLM layer is load-bearing: llm-labelled cases really do reach it ────


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.caught_by == "llm"],
    ids=lambda c: c.id,
)
def test_llm_layer_cases_reach_the_llm(case: ValidatorCase) -> None:
    evidence = [_evidence_for(case)]
    rewrite = _rewrite_for(case)

    with patch(
        "engine.rewrite.validate._call_llm_validator",
        return_value=_mocked_llm_result(case),
    ) as mock_llm:
        result = validate_rewrite(rewrite, evidence)

    mock_llm.assert_called_once()
    assert result.ok is False


# ── Dataset shape itself ─────────────────────────────────────────────────────


def test_dataset_is_well_formed() -> None:
    assert len(CASES) == 30

    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"

    categories_present = {c.category for c in CASES}
    assert categories_present >= _ADVERSARIAL_CATEGORIES, "all six categories must be present"

    legitimate = [c for c in CASES if c.category == "legitimate"]
    assert len(legitimate) >= 10
    assert all(not c.should_reject and c.caught_by == "none" for c in legitimate)

    employment_types = {"employment", "internship", "part_time"}
    legitimate_employment = [
        c
        for c in legitimate
        if c.evidence_overrides.get("evidence_type") in employment_types
    ]
    assert len(legitimate_employment) >= 3, (
        "at least 3 legitimate cases must cite an employment-type record "
        "while using professional language, to prove the scope gate does "
        "not over-fire"
    )
