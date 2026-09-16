"""F5 — hallucination validator (PERSON_B_PLAN_v2.md §5 Phase 3 task 4).

Two layers, in order, and the order is load-bearing:

1. **Deterministic pre-check** (`precheck_rewrite`), which costs nothing: every
   number, year, month-count and capitalized proper noun in the rewrite must
   already appear in the text of at least one cited (`facts_used`) evidence
   record, or the rewrite fails immediately, before any LLM is called. This
   catches the loud failures — an invented year, employer, tool or headcount —
   deterministically and for free.

2. **A separate LLM call** (`_call_llm_validator`), reached only if the
   pre-check passes, that receives only the rewrite and the cited evidence and
   looks for the quiet failure the regex cannot see: a claim that invents no
   new literal token but still overstates the evidence — a status upgrade
   ("worked as a software engineer" for a class project), a scope inflation
   ("led the team" for "participated"), or an unsupported outcome claim
   (PROJECT_SPEC.md §9 rule 2).

Two layers = defensible: a reviewer can point at the pre-check's exact
non-matching token for the loud failures, and at the LLM's own stated
reasoning for the quiet ones — neither layer is asked to do the other's job.

Every rejection, from either layer, is meant to be logged by the caller via
`api.store.store.log_rewrite_rejection` (PERSON_B_PLAN_v2.md §5 Phase 3 task
5, Task 10 of this plan) — this module only judges, it does not log, keeping
it importable and testable with no store dependency.
"""

from __future__ import annotations

import re

from engine.normalize.schema import Evidence
from engine.rewrite import llm, prompts
from engine.rewrite.models import Rewrite, ValidationResult, Violation

__all__ = ["validate_rewrite", "precheck_rewrite"]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
_WORD_RE = re.compile(r"[A-Za-z][a-zA-Z']*")


def _facts_text(rewrite: Rewrite, evidence_records: list[Evidence]) -> str:
    """Every field of every evidence record `rewrite.facts_used` actually
    cites, joined into one lowercase haystack to substring-check claims
    against."""
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    parts: list[str] = []
    for e in cited:
        parts.append(e.source_line)
        parts.extend(e.skills)
        if e.outcome:
            parts.append(e.outcome)
        if e.duration_months is not None:
            parts.append(str(e.duration_months))
        if e.team_size is not None:
            parts.append(str(e.team_size))
    return " ".join(parts).lower()


def _extract_checkable_tokens(text: str) -> list[str]:
    """Numbers (checked regardless of position — a number is a claim wherever
    it sits) and proper-noun-shaped words. Each sentence's first word is
    skipped for the Title-case check, to avoid flagging ordinary
    sentence-initial capitalization ("Coordinated with...") as an invented
    proper noun; an ALL-CAPS acronym is checked at any position, since
    something like "AWS" is exactly as much a claim at a sentence's start as
    in its middle."""
    tokens = list(_NUMBER_RE.findall(text))
    for sentence in _SENTENCE_RE.split(text):
        words = _WORD_RE.findall(sentence)
        for i, word in enumerate(words):
            if _ACRONYM_RE.fullmatch(word) or (i > 0 and word[0].isupper()):
                tokens.append(word)
    return tokens


def precheck_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult | None:
    """The deterministic layer. Returns `None` when the rewrite passes — the
    caller then proceeds to the LLM layer — or a `ValidationResult(ok=False,
    ...)` naming every unsupported token when it does not."""
    haystack = _facts_text(rewrite, evidence_records)
    violations = [
        Violation(claim=token, reason="Not present in any cited evidence record.")
        for token in _extract_checkable_tokens(rewrite.suggested_phrasing)
        if token.lower() not in haystack
    ]
    if not violations:
        return None
    return ValidationResult(ok=False, violations=violations)


def _call_llm_validator(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult:
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    evidence_lines = [prompts.format_evidence_line(e) for e in cited]
    response = llm.call_structured(
        system=prompts.VALIDATE_SYSTEM_PROMPT,
        user=prompts.build_validate_user_prompt(rewrite.suggested_phrasing, evidence_lines),
        tool_name=prompts.VALIDATE_TOOL_NAME,
        tool_description="Report whether the rewrite is a faithful restatement of the evidence.",
        tool_schema=prompts.VALIDATE_TOOL_SCHEMA,
    )
    return ValidationResult(
        ok=bool(response.get("ok")),
        violations=[Violation(**v) for v in response.get("violations", [])],
    )


def validate_rewrite(rewrite: Rewrite, evidence_records: list[Evidence]) -> ValidationResult:
    """Run both layers in order. The LLM layer never runs if the pre-check
    already failed — "costs nothing" only holds if the free check runs first."""
    precheck_failure = precheck_rewrite(rewrite, evidence_records)
    if precheck_failure is not None:
        return precheck_failure
    return _call_llm_validator(rewrite, evidence_records)
