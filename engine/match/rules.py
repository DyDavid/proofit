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


def _classify_action_category(req: Requirement) -> str:
    """Classify a requirement into one of the 4 actionable recommendation categories:
    1. 'experience': Experience & Tenures
    2. 'tools': Tools, Software & Certifications
    3. 'soft_skills': Soft Skills & Behavioral Traits
    4. 'domain': Domain Knowledge & Preferences
    """
    cat = req.category
    text = req.text.lower()
    skill = (req.normalized_skill or "").lower()
    combined = f"{text} {skill}"

    # 3. Soft skills check (check early to avoid false positive on "experience with teamwork" etc.)
    soft_indicators = [
        "detail", "attention to detail", "desire to learn", "accuracy", "commitment",
        "communication", "interpersonal", "teamwork", "collaboration", "problem solving",
        "problem-solving", "critical thinking", "leadership", "work ethic", "adaptability",
        "time management", "fast learner", "motivated", "enthusiastic", "integrity",
        "organized", "organisational", "passion", "analytical thinking", "proactive",
        "negotiation", "presentation", "conflict resolution", "multitask", "self-starter",
        "punctual", "punctuality", "positive attitude", "willingness to learn",
    ]
    if cat == "soft_skill" or any(s in combined for s in soft_indicators):
        return "soft_skills"

    # 1. Experience & Tenures check
    exp_indicators = [
        "year of experience", "years of experience", "years experience", "year experience",
        "yr of exp", "yrs of exp", "years' experience", "internship", "intern",
        "past role", "past roles", "tenure", "work history", "entry-level", "track record",
        "previous experience", "working experience", "hands-on experience", "proven experience",
        "0-1 year", "1-2 year", "2-3 year", "3-5 year", "5+ year", "prior role", "prior work",
    ]
    if cat == "experience" or any(e in combined for e in exp_indicators):
        return "experience"

    # 2. Tools, Software & Certifications check
    tool_indicators = [
        "quickbooks", "excel", "ms excel", "sap", "xero", "word", "ms word", "office",
        "ms office", "powerpoint", "suite", "software", "system", "systems", "tool", "tools",
        "app", "certified", "certification", "cpa", "acca", "cfa", "erp", "crm", "sql",
        "python", "java", "javascript", "typescript", "react", "vue", "angular", "node",
        "git", "docker", "figma", "jira", "computerized", "computerised", "tableau",
        "power bi", "pos", "photoshop", "illustrator", "sage", "peachtree", "odoo",
    ]
    if cat == "certification" or any(t in combined for t in tool_indicators):
        return "tools"

    # 4. Domain Knowledge & Preferences (default for education, tax, standards, language, other)
    return "domain"


def _generate_action_recommendation(
    req: Requirement,
    verdict: Verdict,
    potential_gain: float,
) -> str:
    category_type = _classify_action_category(req)
    skill_label = req.normalized_skill or req.text
    if len(skill_label) > 60:
        skill_label = skill_label[:57].rstrip() + "..."

    combined_text = f"{req.text} {req.normalized_skill or ''}".lower()

    if category_type == "experience":
        # Strategy 1: Experience & Tenures
        # Never recommend building a portfolio or project.
        if "intern" in combined_text:
            rec = "Add previous internship or work entries covering relevant roles, or highlight student consulting and volunteer experience."
        else:
            rec = f"Add previous internship or work entries covering '{skill_label}', or highlight relevant student consulting / volunteer roles."

    elif category_type == "tools":
        # Strategy 2: Tools, Software & Certifications
        # Do not recommend vague capstone projects.
        # Suggest listing practical usage: specific modules used (e.g. AP/AR, bank reconciliation), certifications, or coursework labs.
        if any(w in combined_text for w in ["quickbooks", "accounting system", "ledger", "bookkeeping"]):
            rec = f"List specific {skill_label} tasks performed (e.g., ledger entries, invoice reconciliation) or add relevant software certification."
        elif any(w in combined_text for w in ["excel", "spreadsheet", "office"]):
            rec = f"List specific {skill_label} tasks performed (e.g., pivot tables, VLOOKUP/XLOOKUP, formulas) or add relevant software certification."
        elif "sap" in combined_text or "erp" in combined_text:
            rec = f"List specific {skill_label} modules used (e.g., AP/AR, general ledger) or add relevant system certification."
        elif "certif" in combined_text or req.category == "certification":
            rec = f"List completed {skill_label} credentials, exam progress, or relevant specialized coursework labs."
        else:
            rec = f"List specific practical tasks performed with '{skill_label}' (e.g., core workflows, module usage) or add relevant software certification."

    elif category_type == "soft_skills":
        # Strategy 3: Soft Skills & Behavioral Traits
        # Never suggest 'technical outcomes' for non-technical soft skills.
        # Suggest grounding the trait in verifiable resume metrics: audit error reduction rates, quality control steps, or self-directed continuous learning/courses.
        if any(w in combined_text for w in ["detail", "accuracy", "error", "commit"]):
            rec = "Quantify this trait in your existing bullets (e.g., audited records with 0% error rate, completed quality control steps)."
        elif any(w in combined_text for w in ["learn", "desire", "growth", "curiosity"]):
            rec = "Quantify this trait in your existing bullets (e.g., completed self-paced learning modules, self-directed tax training)."
        else:
            rec = "Quantify this trait in your existing bullets (e.g., audit error reduction rates, quality control steps, or self-directed coursework)."

    else:
        # Strategy 4: Domain Knowledge & Preferences
        # Suggest citing specific local tax codes, academic coursework modules, or specialized case studies analyzed.
        if any(w in combined_text for w in ["tax", "taxation", "vat", "withholding"]):
            rec = "Mention specific coursework or self-study in local tax laws (e.g., monthly VAT returns, withholding tax basics)."
        elif any(w in combined_text for w in ["standard", "gaap", "ifrs", "audit", "compliance", "regulation"]):
            rec = f"Cite specific coursework modules, accounting standards (e.g., IFRS/GAAP), or compliance case studies analyzed for '{skill_label}'."
        elif req.category == "education" or any(w in combined_text for w in ["degree", "major", "bachelor", "diploma"]):
            rec = f"Highlight relevant academic degree coursework, academic honors, or specialized modules in '{skill_label}'."
        elif req.category == "language" or any(w in combined_text for w in ["english", "khmer", "language"]):
            rec = f"List language proficiency levels, standardized scores (e.g., IELTS, TOEFL), or bilingual workplace communication experience for '{skill_label}'."
        else:
            rec = f"Mention specific coursework, academic modules, or specialized case studies analyzed for '{skill_label}'."

    return f"+{potential_gain}% Match Boost: {rec} ({req.priority.capitalize()})"


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

        action_text = _generate_action_recommendation(req, res.verdict, potential_gain)
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

