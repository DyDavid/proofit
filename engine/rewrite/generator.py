"""Rewrite Generator for F5 Hidden Strengths.

Generates suggested phrasing strictly from candidate Evidence records.
Never reads the raw resume or full JD text, ensuring rewrites remain evidence-bound.
"""

from __future__ import annotations

import json
import re
from typing import Any

from engine.normalize.schema import Evidence, Requirement


def _compute_changed_words(current_text: str, suggested_text: str) -> list[str]:
    """Computes words present in suggested_text that are absent from current_text."""
    current_words = set(re.findall(r"\b\w+\b", current_text.lower()))
    suggested_words = re.findall(r"\b\w+\b", suggested_text.lower())
    
    # Filter out stopwords so diff highlights meaningful additions
    stopwords = {"a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "by", "of", "is", "was"}
    diff = []
    for word in suggested_words:
        if word not in current_words and word not in stopwords and word not in diff:
            diff.append(word)
    return diff


def generate_rewrite(
    requirement: Requirement,
    evidence_records: list[Evidence],
    current_phrasing: str | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Generates an evidence-bound rewrite for a requirement based solely on cited evidence records."""
    if not evidence_records:
        raise ValueError("Cannot generate rewrite without evidence_records")

    facts_used = [e.id for e in evidence_records]
    base_evidence = evidence_records[0]
    ref_phrasing = current_phrasing or base_evidence.source_line

    if use_llm:
        try:
            from engine.gemini_client import generate_gemini_text, get_analysis_model

            prompt = f"""You are an expert resume writer specialized in entry-level and technical candidates.
REQUIREMENT TO MATCH:
- Target skill/topic: {requirement.normalized_skill or requirement.text}

CITED CANDIDATE EVIDENCE (Strict Source Material):
{json.dumps([e.model_dump() for e in evidence_records], indent=2)}

ORIGINAL RESUME LINE:
"{ref_phrasing}"

INSTRUCTIONS:
1. Rephrase the original resume line using the STAR method (Action Verb + Specific Task + Technologies + Quantifiable Outcome present in source).
2. Use strong technical keywords aligned with the target skill.
3. ZERO NEW FACTS: Do not invent numbers, dates, tools, metrics, company names, or job titles not in the source evidence.
4. If evidence is a project or coursework, DO NOT claim it was paid commercial employment.
5. Keep the rewrite concise (1 bullet point, under 30 words).
6. Output JSON format ONLY:
{{
  "suggested_phrasing": "string"
}}
"""
            resp_text = generate_gemini_text(
                prompt,
                json_mode=True,
                model_name=get_analysis_model(),
                temperature=0.3,
                thinking_budget=0,
            )
            res_json = json.loads(resp_text)
            suggested = res_json.get("suggested_phrasing", ref_phrasing)
        except Exception:
            # Fallback deterministic rewrite
            suggested = f"Demonstrated {requirement.normalized_skill or requirement.text} through {ref_phrasing}"
    else:
        suggested = f"Demonstrated {requirement.normalized_skill or requirement.text} through {ref_phrasing}"

    changed = _compute_changed_words(ref_phrasing, suggested)

    return {
        "suggested_phrasing": suggested,
        "facts_used": facts_used,
        "changed_words": changed,
    }
