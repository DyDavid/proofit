"""Prompts and tool schemas for the three F5 LLM calls. Kept separate from
detect.py/generate.py/validate.py so the prompt text — the part most likely to
be iterated on for the report — never gets lost inside control flow.
"""

from __future__ import annotations

from typing import Any

from engine.normalize.schema import Evidence

__all__ = [
    "format_evidence_line",
    "DETECT_SYSTEM_PROMPT",
    "DETECT_TOOL_NAME",
    "DETECT_TOOL_SCHEMA",
    "build_detect_user_prompt",
    "GENERATE_SYSTEM_PROMPT",
    "GENERATE_TOOL_NAME",
    "GENERATE_TOOL_SCHEMA",
    "build_generate_user_prompt",
    "VALIDATE_SYSTEM_PROMPT",
    "VALIDATE_TOOL_NAME",
    "VALIDATE_TOOL_SCHEMA",
    "build_validate_user_prompt",
]


def format_evidence_line(evidence: Evidence) -> str:
    """One evidence record as `id: description [type] skills: ... — ...` — the
    only shape any of the three prompts below ever see an Evidence in."""
    parts = [f"{evidence.id}: {evidence.source_line}", f"[{evidence.evidence_type}]"]
    if evidence.skills:
        parts.append(f"skills: {', '.join(evidence.skills)}")
    if evidence.duration_months is not None:
        parts.append(f"duration_months: {evidence.duration_months}")
    if evidence.team_size is not None:
        parts.append(f"team_size: {evidence.team_size}")
    if evidence.outcome:
        parts.append(f"outcome: {evidence.outcome}")
    return " — ".join(parts)


# ── detect_hidden_strengths ─────────────────────────────────────────────────

DETECT_SYSTEM_PROMPT = (
    "You are checking whether a candidate's resume already satisfies a single job "
    "requirement, even if the resume's wording does not match the requirement directly.\n\n"
    "Rules:\n"
    "- You may only point to evidence already in the list given to you. Never invent evidence.\n"
    "- Judge substance, not keywords: an evidence record satisfies the requirement if what it "
    "describes would reasonably count, even in different words.\n"
    "- If no evidence record satisfies the requirement, say so — do not force a match.\n"
    "- Cite exactly one evidence id: the single strongest piece of evidence, if any."
)

DETECT_TOOL_NAME = "report_hidden_strength"
DETECT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "found": {
            "type": "boolean",
            "description": "True if some evidence record satisfies the requirement.",
        },
        "evidence_id": {
            "type": "string",
            "description": "Id of the strongest satisfying evidence record. Required when found is true.",
        },
        "rationale": {
            "type": "string",
            "description": "One sentence: why this evidence satisfies the requirement. Required when found is true.",
        },
    },
    "required": ["found"],
}


def build_detect_user_prompt(requirement_text: str, evidence_lines: list[str]) -> str:
    numbered = "\n".join(evidence_lines)
    return (
        f"Requirement: {requirement_text}\n\n"
        f"Evidence records (id: description):\n{numbered}\n\n"
        "Does any evidence record satisfy this requirement, even if phrased differently?"
    )


# ── generate_rewrite ─────────────────────────────────────────────────────────

GENERATE_SYSTEM_PROMPT = (
    "You rewrite one resume line so it speaks to a requirement's language, without "
    "inventing anything.\n\n"
    "Rules, and they are absolute:\n"
    "- No new numbers. No new durations. No new employers. No new tools or technologies.\n"
    "- You may reorder words, and you may borrow the job post's vocabulary for a skill or "
    "concept already present in the evidence.\n"
    "- You may not change what kind of evidence this is: a class project stays a project, a "
    "volunteer role stays volunteer work. Never imply paid professional employment where the "
    "evidence is coursework, a project, a competition, or volunteering.\n"
    "- Every fact in your rewrite must already be present in the evidence given to you. If you "
    "are not sure a word is grounded in the evidence, leave it out.\n"
    "- Cite every evidence id you actually used in facts_used."
)

GENERATE_TOOL_NAME = "propose_rewrite"
GENERATE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggested_phrasing": {"type": "string"},
        "facts_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Evidence ids (e.g. 'e3') every claim in suggested_phrasing traces to.",
        },
    },
    "required": ["suggested_phrasing", "facts_used"],
}


def build_generate_user_prompt(
    requirement_text: str,
    evidence_lines: list[str],
    tone_notes: list[str] | None = None,
) -> str:
    """Build the user turn for `generate_rewrite`.

    `tone_notes` is F6's optional addition (task 4c): a destination market's
    register and structure guidance (`CountryRules.tone_notes`,
    `engine/country/rules.py`), passed through by `create_rewrites` via
    `rules_for(record.country)`. Optional and default-`None` so every
    existing call site — and every test that asserts on this function's
    output without passing it — is unaffected.

    global-constraints.md's rule 1 ("no invented facts") applies here exactly
    as it does to `requirement_text`: tone notes describe HOW to phrase the
    rewrite, never WHAT the candidate did or has. When present, they are
    appended as their own block, clearly labelled and kept out of the
    evidence section above — so a fabricated-sounding detail inside a tone
    note (e.g. "emphasize 10 years of experience") cannot be mistaken for
    something to cite in `facts_used`.
    """
    numbered = "\n".join(evidence_lines)
    prompt = (
        f"Job requirement (for vocabulary only — never a source of facts): {requirement_text}\n\n"
        f"Evidence records, the ONLY source of facts (id: description):\n{numbered}\n\n"
        "Rewrite the primary evidence line so it speaks to the requirement, using only facts "
        "already present above."
    )
    if tone_notes:
        bullets = "\n".join(f"- {note}" for note in tone_notes)
        prompt += (
            "\n\nStyle guidance for the target market — HOW to phrase this rewrite, "
            "never a source of facts. Nothing below is something the candidate did or "
            "has, and none of it may be cited in facts_used:\n"
            f"{bullets}"
        )
    return prompt


# ── validate_rewrite (LLM layer) ────────────────────────────────────────────

VALIDATE_SYSTEM_PROMPT = (
    "You are a strict fact-checker for a resume rewrite. You already know the rewrite "
    "contains no invented numbers, dates or proper nouns — a separate deterministic check "
    "covers that. Your job is the subtler failure: a rewrite that invents no new literal "
    "token but still claims more than the evidence supports.\n\n"
    "Look specifically for:\n"
    "- Status upgrades: unpaid, academic or informal work described as if it were paid "
    'professional employment (e.g. "worked as a software engineer" for a class project).\n'
    "- Scope inflation: a claim of responsibility, outcome or independence broader than the "
    'evidence states (e.g. "led the team" when the evidence says "participated").\n'
    "- Causal or outcome claims the evidence does not support.\n\n"
    "If the rewrite is a faithful restatement of the evidence, say so. Do not invent a "
    "violation to have something to report."
)

VALIDATE_TOOL_NAME = "report_validation"
VALIDATE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["claim", "reason"],
            },
        },
    },
    "required": ["ok", "violations"],
}


def build_validate_user_prompt(suggested_phrasing: str, evidence_lines: list[str]) -> str:
    numbered = "\n".join(evidence_lines)
    return (
        f"Rewrite to check: {suggested_phrasing}\n\n"
        f"Evidence it must be grounded in (id: description):\n{numbered}"
    )
