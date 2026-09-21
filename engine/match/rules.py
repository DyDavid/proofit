"""Deterministic rules engine and coverage algorithm for matching.

OWNER: Person A (Dy David)

Enforces non-negotiable rules from PROJECT_SPEC.md §9:
- Rule 2 (F4): Non-employment evidence (coursework, project, volunteer, competition)
  can NEVER yield 'proven' for 'experience' requirements. Forced to 'partial'.
- Coverage score calculation:
  - Requirement weights: Required = 1.0, Preferred = 0.4
  - Verdict scores: Proven = 1.0, Partial = 0.5, Missing = 0.0
"""

from __future__ import annotations

import logging

from engine.normalize.schema import (
    NON_EMPLOYMENT_EVIDENCE,
    Job,
    MatchResult,
    RealismVerdict,
    Requirement,
    Resume,
    Verdict,
)

logger = logging.getLogger(__name__)


def enforce_no_scope_inflation(
    results: list[MatchResult],
    job: Job,
    resume: Resume,
) -> list[MatchResult]:
    """Enforce that non-employment evidence alone cannot yield 'proven' on experience requirements."""
    req_map = {r.id: r for r in job.requirements}
    adjusted_results: list[MatchResult] = []

    for res in results:
        req = req_map.get(res.requirement_id)
        if not req:
            adjusted_results.append(res)
            continue

        if req.category == "experience" and res.verdict == "proven":
            # Check if all cited evidence is non-employment
            cited_ev = [resume.evidence_by_id(ev_id) for ev_id in res.evidence_ids]
            valid_ev = [e for e in cited_ev if e is not None]

            if valid_ev and all(e.evidence_type in NON_EMPLOYMENT_EVIDENCE for e in valid_ev):
                logger.info(
                    "Rule 2 triggered for requirement %s: non-employment evidence downgraded 'proven' to 'partial'.",
                    req.id,
                )
                adjusted_results.append(
                    MatchResult(
                        requirement_id=res.requirement_id,
                        verdict="partial",
                        evidence_ids=res.evidence_ids,
                        reasoning=(
                            f"[Scope Rule F4] Downgraded from proven to partial: Non-employment evidence "
                            f"({', '.join(e.evidence_type for e in valid_ev)}) cannot fully prove an experience requirement."
                        ),
                        confidence=res.confidence,
                    )
                )
                continue

        adjusted_results.append(res)

    return adjusted_results


def calculate_coverage(
    results: list[MatchResult],
    job: Job,
) -> tuple[float, float]:
    """Calculate weighted coverage_score (all reqs) and coverage_required_only (required reqs only).

    Returns:
        (coverage_score, coverage_required_only) as float percentages 0.0 – 100.0.
    """
    req_map = {r.id: r for r in job.requirements}
    verdict_scores: dict[Verdict, float] = {
        "proven": 1.0,
        "partial": 0.5,
        "missing": 0.0,
    }

    total_weight = 0.0
    weighted_score = 0.0

    req_total_weight = 0.0
    req_weighted_score = 0.0

    for res in results:
        req = req_map.get(res.requirement_id)
        if not req:
            continue

        weight = 1.0 if req.priority == "required" else 0.4
        v_score = verdict_scores.get(res.verdict, 0.0)

        total_weight += weight
        weighted_score += weight * v_score

        if req.priority == "required":
            req_total_weight += weight
            req_weighted_score += weight * v_score

    coverage_score = round((weighted_score / total_weight) * 100.0, 1) if total_weight > 0 else 0.0
    coverage_required_only = (
        round((req_weighted_score / req_total_weight) * 100.0, 1) if req_total_weight > 0 else 0.0
    )

    return coverage_score, coverage_required_only


def generate_quantified_priority_actions(
    results: list[MatchResult],
    job: Job,
) -> list[str]:
    """Generate rank-ordered action items sorted by potential % match score boost."""
    req_map = {r.id: r for r in job.requirements}
    verdict_scores: dict[Verdict, float] = {"proven": 1.0, "partial": 0.5, "missing": 0.0}

    total_weight = sum(1.0 if r.priority == "required" else 0.4 for r in job.requirements)
    if total_weight == 0:
        return []

    action_candidates: list[tuple[float, str]] = []

    for res in results:
        req = req_map.get(res.requirement_id)
        if not req or res.verdict == "proven":
            continue

        weight = 1.0 if req.priority == "required" else 0.4
        current_score = verdict_scores.get(res.verdict, 0.0)
        # Potential gain if upgraded to proven (1.0)
        potential_gain = round(((1.0 - current_score) * weight / total_weight) * 100.0, 1)

        skill_label = req.normalized_skill or req.text
        if len(skill_label) > 60:
            skill_label = skill_label[:57] + "..."

        if res.verdict == "missing":
            if req.category == "experience":
                action_text = f"+{potential_gain}% Match Boost: Build a project or portfolio piece demonstrating '{skill_label}' ({req.priority.capitalize()})"
            elif req.category == "education":
                action_text = f"+{potential_gain}% Match Boost: Highlight relevant degree or specialized coursework in '{skill_label}' ({req.priority.capitalize()})"
            else:
                action_text = f"+{potential_gain}% Match Boost: Add coursework or capstone project evidence for '{skill_label}' ({req.priority.capitalize()})"
        else:  # partial
            action_text = f"+{potential_gain}% Match Boost: Strengthen '{skill_label}' bullet points with specific technical outcomes ({req.priority.capitalize()})"

        action_candidates.append((potential_gain, action_text))

    # Sort descending by % boost
    action_candidates.sort(key=lambda x: x[0], reverse=True)
    return [action for _, action in action_candidates[:5]]


def evaluate_realism(
    results: list[MatchResult],
    job: Job,
    resume: Resume,
) -> tuple[RealismVerdict, str]:
    """Determine realism verdict and concise explanation."""
    req_map = {r.id: r for r in job.requirements}
    required_results = [
        res for res in results
        if res.requirement_id in req_map and req_map[res.requirement_id].priority == "required"
    ]

    missing_required = [res for res in required_results if res.verdict == "missing"]
    proven_required = [res for res in required_results if res.verdict == "proven"]

    # Check experience gap (e.g. JD requires 4+ years for fresh grad)
    if job.years_exp_required and job.years_exp_required >= 4.0 and resume.total_years_work < 1.0:
        return (
            "unrealistic",
            f"The job requires {job.years_exp_required:.0f}+ years of experience, but candidate profile shows entry-level / fresh graduate background.",
        )

    if len(missing_required) >= 3 or (len(required_results) > 0 and len(missing_required) / len(required_results) > 0.4):
        return (
            "unrealistic",
            f"The candidate is missing {len(missing_required)} core required requirements. Significant skill gaps exist for an immediate fit.",
        )

    if len(proven_required) >= len(required_results) * 0.6 and len(missing_required) == 0:
        return (
            "strong_fit",
            "The candidate satisfies all required criteria with solid proven skills and project evidence.",
        )

    return (
        "stretch",
        "The candidate meets key required criteria partially through academic/project evidence, making this a viable stretch opportunity.",
    )

