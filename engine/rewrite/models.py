"""Internal data models for the F5 rewrite pipeline.

These never cross into `engine/normalize/schema.py` or `web/lib/types.ts` — the
only F5 output that reaches the UI is a fully-validated
`engine.normalize.schema.HiddenStrength`, appended to `Match.hidden_strengths`
by the orchestration in `api/routes/analyses.py` (Task 10). Everything here is
intermediate plumbing between `detect_hidden_strengths`, `generate_rewrite` and
`validate_rewrite`.

A local `_Base` rather than importing `engine.normalize.schema`'s private one:
that name is private, and `schema.py` is provisional until CP1
(PERSON_B_PLAN_v2.md §2) — decoupling from it means Person A's CP1 replacement
cannot break this package by renaming or removing a symbol it never needed to
share.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["HiddenStrengthCandidate", "Rewrite", "Violation", "ValidationResult"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HiddenStrengthCandidate(_Base):
    """One `detect_hidden_strengths` finding: a requirement + the evidence
    record an LLM judged satisfies it despite how the resume phrases it."""

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    evidence_id: str = Field(..., pattern=r"^e\d+$")
    rationale: str = Field(
        ..., min_length=1, description="One sentence: why this evidence satisfies the requirement."
    )


class Rewrite(_Base):
    """One `generate_rewrite` output, before validation."""

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    evidence_id: str = Field(
        ..., pattern=r"^e\d+$", description="The primary evidence this rewrite is anchored to."
    )
    suggested_phrasing: str = Field(..., min_length=1)
    facts_used: list[str] = Field(..., min_length=1, description="Evidence.id values cited.")
    changed_words: list[str] = Field(default_factory=list)


class Violation(_Base):
    claim: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ValidationResult(_Base):
    """`validate_rewrite`'s verdict. `ok=False` should always carry at least
    one violation in practice — that is what the rejection log records — but
    this is not schema-enforced, since an `ok=True` result legitimately has
    none."""

    ok: bool
    violations: list[Violation] = Field(default_factory=list)

    @property
    def as_log_violations(self) -> list[dict[str, str]]:
        return [v.model_dump() for v in self.violations]
