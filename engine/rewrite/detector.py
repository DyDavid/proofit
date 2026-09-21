"""Hidden Strengths Detector for F5.

Scans match results for requirement gaps (partial/missing) where candidate evidence
contains unphrased or poorly highlighted skills, generates evidence-bound rewrites,
validates them, and logs any rejections.
"""

from __future__ import annotations

from typing import Any

from engine.normalize.schema import HiddenStrength, Match, Resume
from engine.rewrite.generator import generate_rewrite
from engine.rewrite.rejection_log import log_rejection
from engine.rewrite.validator import validate_rewrite


def detect_hidden_strengths(
    match: Match,
    resume: Resume,
    max_strengths: int = 2,
    use_llm: bool = True,
) -> list[HiddenStrength]:
    """Detects hidden strengths for requirement gaps in a match result."""
    hidden_strengths: list[HiddenStrength] = []

    if not match.job or not match.results:
        return []

    req_map = {r.id: r for r in match.job.requirements}

    for res in match.results:
        if len(hidden_strengths) >= max_strengths:
            break

        if res.verdict not in ("partial", "missing"):
            continue

        req = req_map.get(res.requirement_id)
        if not req:
            continue

        # Look for candidate evidence matching the requirement skill/text
        target_skill = (req.normalized_skill or "").lower()
        candidate_evidences = []

        for ev in resume.evidence:
            ev_text = f"{ev.source_line} {' '.join(ev.skills)}".lower()
            if target_skill and target_skill in ev_text:
                candidate_evidences.append(ev)
            elif not target_skill and any(w in ev_text for w in req.text.lower().split() if len(w) > 4):
                candidate_evidences.append(ev)

        if not candidate_evidences and resume.evidence:
            # Fall back to first cited or first available evidence for partials
            if res.evidence_ids:
                candidate_evidences = [e for e in resume.evidence if e.id in res.evidence_ids]
            if not candidate_evidences:
                candidate_evidences = [resume.evidence[0]]

        if not candidate_evidences:
            continue

        primary_ev = candidate_evidences[0]
        current_phrasing = primary_ev.source_line

        # Generate rewrite attempt
        gen_data = generate_rewrite(
            requirement=req,
            evidence_records=candidate_evidences,
            current_phrasing=current_phrasing,
            use_llm=use_llm,
        )

        # Deterministic validation pass (zero API token cost)
        val_result = validate_rewrite(
            suggested_phrasing=gen_data["suggested_phrasing"],
            evidence_records=candidate_evidences,
            use_llm=False,
        )

        if val_result.ok:
            hs = HiddenStrength(
                requirement_id=req.id,
                evidence_id=primary_ev.id,
                current_phrasing=current_phrasing,
                suggested_phrasing=gen_data["suggested_phrasing"],
                facts_used=gen_data["facts_used"],
                changed_words=gen_data["changed_words"],
            )
            hidden_strengths.append(hs)
        else:
            # Log initial rejection
            log_rejection(
                requirement_id=req.id,
                suggested_phrasing=gen_data["suggested_phrasing"],
                violations=val_result.violations,
                evidence_ids=[e.id for e in candidate_evidences],
                retry_succeeded=False,
            )

            # Retry once with fallback deterministic generator
            fallback_gen = generate_rewrite(
                requirement=req,
                evidence_records=candidate_evidences,
                current_phrasing=current_phrasing,
                use_llm=False,
            )
            val_retry = validate_rewrite(
                suggested_phrasing=fallback_gen["suggested_phrasing"],
                evidence_records=candidate_evidences,
                use_llm=False,
            )

            if val_retry.ok:
                hs = HiddenStrength(
                    requirement_id=req.id,
                    evidence_id=primary_ev.id,
                    current_phrasing=current_phrasing,
                    suggested_phrasing=fallback_gen["suggested_phrasing"],
                    facts_used=fallback_gen["facts_used"],
                    changed_words=fallback_gen["changed_words"],
                )
                hidden_strengths.append(hs)
                # Log success on retry
                log_rejection(
                    requirement_id=req.id,
                    suggested_phrasing=gen_data["suggested_phrasing"],
                    violations=val_result.violations,
                    evidence_ids=[e.id for e in candidate_evidences],
                    retry_succeeded=True,
                )

    return hidden_strengths
