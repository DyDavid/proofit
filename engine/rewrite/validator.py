"""Hallucination Validator for F5 Evidence-Bound Rewrites.

Enforces two layers of defense:
1. Deterministic Pre-check:
   - Verifies numbers, dates, team sizes, and proper nouns in the suggested phrasing
     exist in the cited evidence records.
   - Verifies non-employment evidence does not use forbidden scope-inflating terms (forbidden.json).
2. LLM Validator:
   - Secondary check that validates claims against cited evidence records.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, NamedTuple

from engine.normalize.schema import NON_EMPLOYMENT_EVIDENCE, Evidence


class ValidationResult(NamedTuple):
    ok: bool
    violations: list[dict[str, str]]


_FORBIDDEN_FILE = Path(__file__).parent / "forbidden.json"
_FORBIDDEN_WORDS: list[str] = []
if _FORBIDDEN_FILE.is_file():
    try:
        with open(_FORBIDDEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _FORBIDDEN_WORDS = data.get("forbidden_words", [])
    except Exception:
        pass


def _extract_numbers(text: str) -> list[str]:
    """Extract numeric patterns like 3, 30, 2023, 4, etc."""
    return re.findall(r"\b\d+(?:\.\d+)?\b", text)


def _extract_proper_nouns(text: str) -> list[str]:
    """Extract capitalized words or tech terms that might represent proper nouns/tools/institutions,
    ignoring standard sentence starters or common English words.
    """
    words = re.findall(r"\b[A-Za-z0-9+#./-]+\b", text)
    common_words = {
        "the", "a", "an", "in", "on", "at", "with", "by", "for", "to", "from",
        "using", "built", "developed", "created", "constructed", "utilized",
        "engineered", "assisted", "participated", "during", "team", "project",
        "month", "months", "year", "years", "experience", "application",
        "system", "web", "frontend", "backend", "interfaces", "developer",
        "intern", "academic", "tracker", "delivery", "tracking", "interactive",
        "and", "or", "of", "is", "was", "were", "been", "being", "have", "has",
        "had", "do", "does", "did", "doing", "can", "could", "should", "would"
    }
    terms = []
    for w in words:
        wl = w.lower()
        if wl not in common_words and not wl.isdigit():
            # Check if it looks like a technical term or proper noun
            if any(char.isupper() for char in w) or "/" in w or "-" in w or "." in w or w.isupper():
                terms.append(w)
    return terms


def validate_rewrite(
    suggested_phrasing: str,
    evidence_records: list[Evidence],
    use_llm: bool = False,
) -> ValidationResult:
    """Validates that suggested_phrasing introduces no new claims, numbers, dates,
    or forbidden scope-inflating terms.
    """
    violations: list[dict[str, str]] = []

    if not suggested_phrasing.strip():
        return ValidationResult(ok=False, violations=[{"claim": "", "reason": "Empty phrasing"}])

    # Collect all text content and metadata from supporting evidence
    evidence_text_corpus = " ".join(
        [
            f"{e.source_line} {' '.join(e.skills)} {e.outcome or ''} {e.evidence_type}"
            f" duration:{e.duration_months or ''} team:{e.team_size or ''}"
            for e in evidence_records
        ]
    )

    # 1. Scope inflation check for non-employment evidence
    is_non_employment = any(e.evidence_type in NON_EMPLOYMENT_EVIDENCE for e in evidence_records)
    if is_non_employment:
        suggested_lower = suggested_phrasing.lower()
        for word in _FORBIDDEN_WORDS:
            if word in suggested_lower:
                violations.append(
                    {
                        "claim": word,
                        "reason": f"Forbidden term '{word}' used for non-employment evidence type.",
                    }
                )

    # 2. Number & Date Verification
    suggested_numbers = _extract_numbers(suggested_phrasing)
    evidence_numbers = set(_extract_numbers(evidence_text_corpus))

    for num in suggested_numbers:
        if num not in evidence_numbers:
            violations.append(
                {
                    "claim": num,
                    "reason": f"Number '{num}' in rewrite is absent from cited evidence records.",
                }
            )

    # 3. Tool / Proper Noun Insertion Verification
    suggested_terms = _extract_proper_nouns(suggested_phrasing)
    evidence_corpus_lower = evidence_text_corpus.lower()
    for term in suggested_terms:
        # Check if term is hyphenated duration like '6-month'
        m = re.match(r"^(\d+)-(?:month|year|day)s?$", term, re.IGNORECASE)
        if m:
            num = m.group(1)
            if num in evidence_numbers:
                continue
        if term.lower() not in evidence_corpus_lower:
            violations.append(
                {
                    "claim": term,
                    "reason": f"Technical term/tool '{term}' in rewrite is absent from cited evidence records.",
                }
            )

    # 4. Specific role/credential inflation check
    lower_phrasing = suggested_phrasing.lower()
    for role_word in ["led", "managed", "supervised", "directed", "founded"]:
        if role_word in lower_phrasing and role_word not in evidence_corpus_lower:
            has_lead = any(e.team_size and e.team_size > 1 for e in evidence_records)
            if not has_lead:
                violations.append(
                    {
                        "claim": role_word,
                        "reason": f"Leadership claim '{role_word}' not backed by evidence records.",
                    }
                )

    # If LLM validation is requested and deterministic checks passed
    if use_llm and not violations:
        try:
            from engine.gemini_client import generate_gemini_text, get_analysis_model

            prompt = f"""You are a strict resume hallucination validator.
CITED EVIDENCE RECORDS:
{json.dumps([e.model_dump() for e in evidence_records], indent=2)}

SUGGESTED PHRASING:
"{suggested_phrasing}"

Check if SUGGESTED PHRASING introduces any unbacked claims, invented tools, altered durations, inflated titles, or unverified achievements not present in CITED EVIDENCE RECORDS.

Return ONLY a JSON object:
{{
  "ok": true/false,
  "violations": [
     {{"claim": "string", "reason": "string"}}
  ]
}}
"""
            resp_text = generate_gemini_text(
                prompt,
                json_mode=True,
                model_name=get_analysis_model(),
                temperature=0.0,
                thinking_budget=0,
            )
            llm_res = json.loads(resp_text)
            if not llm_res.get("ok", True):
                for v in llm_res.get("violations", []):
                    violations.append(v)
        except Exception:
            # Fall back safely to deterministic check result
            pass

    return ValidationResult(ok=len(violations) == 0, violations=violations)
