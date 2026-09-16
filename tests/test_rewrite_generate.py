from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.country.rules import rules_for
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


def test_generate_rewrite_tone_notes_are_labelled_style_guidance_not_facts() -> None:
    """Task 4 (c): `build_generate_user_prompt` gains an optional tone-notes
    block, wired through `generate_rewrite`. global-constraints.md's rule 1
    ("no invented facts") means a tone note must never be mistaken for a
    source of facts — including a tone note that itself smuggles in a
    fabricated, specific detail the candidate never had. Two structural
    checks, both deterministic (the LLM call is mocked throughout, per
    global-constraints.md): the fabricated fact must not land inside the
    prompt's evidence section, where the model is told facts must trace to,
    and it must not leak into the generated `Rewrite.facts_used` — the field
    `HiddenStrength.facts_used` persists straight from here."""
    requirement = Requirement(
        id="r1", text="Experience with React", category="hard_skill", priority="required"
    )
    evidence = Evidence(
        id="e1",
        source_line="Built a dashboard for a university course project.",
        evidence_type="project",
        skills=["React"],
    )
    fabricated_tone_note = (
        "Emphasize the candidate's 12 years of professional React experience."
    )

    captured: dict[str, str] = {}

    def _capture_prompt(*, user: str, **_kwargs: object) -> dict[str, object]:
        captured["user"] = user
        return {
            "suggested_phrasing": "Built a React dashboard for a university course project.",
            "facts_used": ["e1"],
        }

    with patch("engine.rewrite.generate.llm.call_structured", side_effect=_capture_prompt):
        rewrite = generate_rewrite(requirement, [evidence], tone_notes=[fabricated_tone_note])

    prompt = captured["user"]
    assert fabricated_tone_note in prompt, "tone note should reach the prompt at all"

    evidence_section, _, style_section = prompt.partition("Style guidance")
    assert fabricated_tone_note not in evidence_section, (
        "a tone note must never appear inside the evidence section — the part of "
        "the prompt the model is told facts must trace to"
    )
    assert style_section, "the tone-notes block must be its own clearly labelled section"
    assert "never a source of facts" in style_section.lower()

    # What HiddenStrength.facts_used actually persists (api/routes/analyses.py's
    # _append_hidden_strength) must never contain the fabricated fact.
    assert rewrite.facts_used == ["e1"]
    assert not any("12 years" in fact for fact in rewrite.facts_used)


def test_generate_rewrite_works_when_destination_has_no_country_rules() -> None:
    """The UI's "other" destination has no CountryRules — `rules_for("other")`
    returns `None` by design (engine/country/rules.py). `create_rewrites`
    (api/routes/analyses.py) then calls `generate_rewrite(..., tone_notes=None)`.
    That must not be a special case generate_rewrite chokes on — `None` is
    the parameter's own default."""
    assert rules_for("other") is None  # documents the precondition this test guards

    requirement = Requirement(
        id="r1", text="Experience with React", category="hard_skill", priority="required"
    )
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
        rewrite = generate_rewrite(requirement, [evidence], tone_notes=None)

    assert rewrite.facts_used == ["e1"]
    assert rewrite.suggested_phrasing == "Built a React dashboard for a university course project."
