from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.rewrite.models import HiddenStrengthCandidate, Rewrite, ValidationResult


def test_rewrite_requires_at_least_one_fact_used() -> None:
    with pytest.raises(ValidationError):
        Rewrite(
            requirement_id="r1",
            evidence_id="e1",
            suggested_phrasing="Built a dashboard.",
            facts_used=[],
        )


def test_validation_result_defaults_to_no_violations() -> None:
    result = ValidationResult(ok=True)
    assert result.violations == []


def test_hidden_strength_candidate_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HiddenStrengthCandidate.model_validate(
            {"requirement_id": "r1", "evidence_id": "e1", "rationale": "fits", "extra": "nope"}
        )
