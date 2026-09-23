"""F5 — hallucination validator (PERSON_B_PLAN_v2.md §5 Phase 3 task 4;
extended to a third layer in Phase 4 hardening task 1).

Three layers, in order, and the order is load-bearing:

1. **Deterministic scope-inflation gate** (`precheck_scope_inflation`), which
   also costs nothing and runs first: PROJECT_SPEC.md §9 rule 2 ("no scope
   inflation") enforced as code rather than as a prompt instruction. It fires
   only when *every* evidence record the rewrite cites in `facts_used` is
   non-employment (`coursework`, `project`, `competition`, `volunteer`) *and*
   the rewrite's phrasing contains a forbidden phrase from
   `engine/rewrite/forbidden.json` (e.g. "professional", "worked at"). If even
   one cited record is `employment`, `internship` or `part_time`, professional
   language may be legitimately supported by that record, so the gate stays
   silent and defers the judgement call to the LLM layer.

2. **Deterministic pre-check** (`precheck_rewrite`), which also costs
   nothing: every number, year, month-count and capitalized proper noun in the
   rewrite must already appear in the text of at least one cited
   (`facts_used`) evidence record, or the rewrite fails immediately, before
   any LLM is called. This catches the loud failures — an invented year,
   employer, tool or headcount — deterministically and for free.

3. **A separate LLM call** (`_call_llm_validator`), reached only if both
   deterministic layers pass, that receives only the rewrite and the cited
   evidence and looks for the quiet failure neither regex layer can see: a
   claim that invents no new literal token and uses no forbidden phrase but
   still overstates the evidence — a status upgrade phrased without any of
   the gate's fixed wordlist, a scope inflation ("led the team" for
   "participated"), or an unsupported outcome claim.

Three layers = defensible: a reviewer can point at the scope gate's exact
forbidden phrase, or the pre-check's exact non-matching token, for the loud
failures, and at the LLM's own stated reasoning for the quiet ones — no layer
is asked to do another's job.

Every rejection, from any layer, is meant to be logged by the caller via
`api.store.store.log_rewrite_rejection` (PERSON_B_PLAN_v2.md §5 Phase 3 task
5, Task 10 of this plan) — this module only judges, it does not log, keeping
it importable and testable with no store dependency.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from engine.normalize.schema import Evidence
from engine.rewrite import llm, prompts
from engine.rewrite.models import Rewrite, ValidationResult, Violation

__all__ = [
    "validate_rewrite",
    "precheck_rewrite",
    "precheck_scope_inflation",
    "load_forbidden",
    "ForbiddenConfig",
    "ForbiddenPhrase",
]

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
_WORD_RE = re.compile(r"[A-Za-z][a-zA-Z']*")

FORBIDDEN_PATH = Path(__file__).resolve().parent / "forbidden.json"


class _ForbiddenBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class ForbiddenPhrase(_ForbiddenBase):
    phrase: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ForbiddenConfig(_ForbiddenBase):
    version: str = Field(..., min_length=1)
    applies_to_evidence_types: list[str] = Field(..., min_length=1)
    forbidden_phrases: list[ForbiddenPhrase] = Field(..., min_length=1)


@lru_cache(maxsize=1)
def load_forbidden() -> ForbiddenConfig:
    return ForbiddenConfig.model_validate(json.loads(FORBIDDEN_PATH.read_text(encoding="utf-8")))


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


def precheck_scope_inflation(
    rewrite: Rewrite, evidence_records: list[Evidence]
) -> ValidationResult | None:
    """PROJECT_SPEC.md §9 rule 2, as code rather than as a prompt instruction.

    Fires only when *every* cited evidence record is non-employment. One cited
    `employment` / `internship` / `part_time` record can legitimately support
    professional language, and deciding that is the LLM layer's job, not this
    one's — a deterministic gate should only reject what is unambiguous.
    """
    config = load_forbidden()
    cited = [e for e in evidence_records if e.id in rewrite.facts_used]
    if not cited:
        return None
    if not all(e.evidence_type in config.applies_to_evidence_types for e in cited):
        return None

    haystack = rewrite.suggested_phrasing.lower()
    violations = [
        Violation(claim=entry.phrase, reason=entry.reason)
        for entry in config.forbidden_phrases
        if re.search(rf"\b{re.escape(entry.phrase.lower())}", haystack)
    ]
    if not violations:
        return None
    return ValidationResult(ok=False, violations=violations)


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
    """Run all three layers in order: the scope-inflation gate, then the
    deterministic pre-check, then the LLM. Each later layer only runs if
    every earlier one already passed — "costs nothing" only holds if the free
    checks run first."""
    scope_failure = precheck_scope_inflation(rewrite, evidence_records)
    if scope_failure is not None:
        return scope_failure
    precheck_failure = precheck_rewrite(rewrite, evidence_records)
    if precheck_failure is not None:
        return precheck_failure
    return _call_llm_validator(rewrite, evidence_records)
