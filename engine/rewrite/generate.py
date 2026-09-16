"""F5 — evidence-bound rewrite generator (PERSON_B_PLAN_v2.md §5 Phase 3 task 3).

`generate_rewrite`'s input is evidence records ONLY — never the raw resume
text, never the JD beyond the requirement's own wording used for vocabulary.
Rewriting toward the JD's wording from the JD itself, rather than from what the
evidence actually says, is how this feature would become a lying machine
(engine/rewrite/__init__.py).
"""

from __future__ import annotations

import re

from engine.normalize.schema import Evidence, Requirement
from engine.rewrite import llm, prompts
from engine.rewrite.models import Rewrite

__all__ = ["generate_rewrite"]

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _changed_words(current_phrasing: str, suggested_phrasing: str) -> list[str]:
    """Words in `suggested_phrasing` absent from `current_phrasing`,
    case-insensitively, in order, without duplicates — powers the word-level
    diff highlight (`HiddenStrength.changed_words`, Phase 4.3's before/after
    UI). Computed here, deterministically, rather than asked of the model —
    `HiddenStrength.changed_words`'s own docstring: "keeps the UI dumb and the
    diff reproducible.\""""
    current_words = {w.lower() for w in _WORD_RE.findall(current_phrasing)}
    seen: set[str] = set()
    changed: list[str] = []
    for word in _WORD_RE.findall(suggested_phrasing):
        lowered = word.lower()
        if lowered not in current_words and lowered not in seen:
            seen.add(lowered)
            changed.append(word)
    return changed


def generate_rewrite(
    requirement: Requirement,
    evidence_records: list[Evidence],
    tone_notes: list[str] | None = None,
) -> Rewrite:
    """Rewrite the primary evidence record's line toward one requirement.

    Args:
        requirement: Supplies vocabulary only — its own words are never a
            source of facts the rewrite may add.
        evidence_records: The only source of facts. `evidence_records[0]` is
            the anchor: its `source_line` is `current_phrasing` for the
            `changed_words` diff, and its `id` becomes `Rewrite.evidence_id`.
            Any further records are extra context the model may also cite in
            `facts_used`.
        tone_notes: F6's destination market register/structure guidance
            (`CountryRules.tone_notes`), or `None` when the caller has none —
            either `rules_for` returned `None` (the UI's "other" destination,
            a normal outcome, not an error) or no country was resolved.
            Passed straight through to `build_generate_user_prompt`, which is
            what actually labels it as phrasing guidance, never facts.

    Raises:
        ValueError: if `evidence_records` is empty — there is nothing to
            anchor the rewrite to.
    """
    if not evidence_records:
        raise ValueError("generate_rewrite requires at least one evidence record")

    anchor = evidence_records[0]
    evidence_lines = [prompts.format_evidence_line(e) for e in evidence_records]

    response = llm.call_structured(
        system=prompts.GENERATE_SYSTEM_PROMPT,
        user=prompts.build_generate_user_prompt(requirement.text, evidence_lines, tone_notes),
        tool_name=prompts.GENERATE_TOOL_NAME,
        tool_description="Propose a rewrite grounded only in the given evidence.",
        tool_schema=prompts.GENERATE_TOOL_SCHEMA,
    )

    suggested_phrasing = response["suggested_phrasing"]
    return Rewrite(
        requirement_id=requirement.id,
        evidence_id=anchor.id,
        suggested_phrasing=suggested_phrasing,
        facts_used=list(response["facts_used"]),
        changed_words=_changed_words(anchor.source_line, suggested_phrasing),
    )
