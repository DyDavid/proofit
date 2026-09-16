from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.normalize.schema import Evidence, Requirement
from engine.rewrite.generate import generate_rewrite


def test_generate_rewrite_computes_changed_words_deterministically() -> None:
    requirement = Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required")
    evidence = Evidence(
        id="e1",
        source_line="Built a dashboard for a university course project.",
        evidence_type="project",
        skills=["React"],
    )

    with patch(
        "engine.rewrite.generate.llm.call_structured",
        return_value={
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        },
    ):
        rewrite = generate_rewrite(requirement, [evidence])

    assert rewrite.requirement_id == "r1"
    assert rewrite.evidence_id == "e1"
    assert rewrite.facts_used == ["e1"]
    assert rewrite.changed_words == ["React"]


def test_generate_rewrite_requires_at_least_one_evidence_record() -> None:
    requirement = Requirement(id="r1", text="Experience with React", category="hard_skill", priority="required")
    with pytest.raises(ValueError):
        generate_rewrite(requirement, [])
