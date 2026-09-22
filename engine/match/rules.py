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


import re


def _has_kw(text: str, keywords: list[str]) -> bool:
    """Check if any keyword is present with word boundary protection for short terms."""
    for kw in keywords:
        if len(kw) <= 5 or not any(c in kw for c in " -/"):
            if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
                return True
        else:
            if kw.lower() in text.lower():
                return True
    return False


def _is_boilerplate_or_eligibility(text: str) -> bool:
    """Check if requirement is an eligibility statement, persona disclaimer, or hiring boilerplate."""
    patterns = [
        "encouraged to apply", "fresh graduate", "fresh graduates", "entry-level candidate",
        "entry level candidate", "equal opportunity", "authorized to work", "work authorization",
        "right to work", "background check", "drug test", "willing to relocate",
        "able to commute", "legally eligible", "all genders", "disability",
    ]
    return _has_kw(text, patterns)


def _classify_action_category(req: Requirement) -> str:
    """Classify a requirement into one of the actionable recommendation categories:
    1. 'experience': Experience & Tenures
    2. 'tools': Tools, Software & Technical Platforms
    3. 'soft_skills': Soft Skills & Behavioral Traits
    4. 'domain': Domain Knowledge, Standards & Functional Competencies
    """
    cat = req.category
    text = req.text.lower()
    skill = (req.normalized_skill or "").lower()
    combined = f"{text} {skill}"

    # 1. Soft skills check (check early to avoid false positive on "experience with teamwork" etc.)
    soft_indicators = [
        "detail", "attention to detail", "desire to learn", "accuracy", "commitment",
        "communication", "interpersonal", "teamwork", "collaboration", "problem solving",
        "problem-solving", "critical thinking", "leadership", "work ethic", "adaptability",
        "time management", "fast learner", "motivated", "enthusiastic", "integrity",
        "organized", "organisational", "passion", "analytical thinking", "proactive",
        "negotiation", "presentation", "conflict resolution", "multitask", "self-starter",
        "punctual", "punctuality", "positive attitude", "willingness to learn",
    ]
    if cat == "soft_skill" or _has_kw(combined, soft_indicators):
        return "soft_skills"

    # 2. Experience & Tenures check
    exp_indicators = [
        "year of experience", "years of experience", "years experience", "year experience",
        "yr of exp", "yrs of exp", "years' experience", "internship", "intern",
        "past role", "past roles", "tenure", "work history", "entry-level", "track record",
        "previous experience", "working experience", "hands-on experience", "proven experience",
        "0-1 year", "1-2 year", "2-3 year", "3-5 year", "5+ year", "prior role", "prior work",
    ]
    if cat == "experience" or _has_kw(combined, exp_indicators):
        return "experience"

    # 3. Tools, Software & Technical Platforms
    tool_indicators = [
        "quickbooks", "excel", "ms excel", "sap", "xero", "word", "ms word", "office",
        "ms office", "powerpoint", "suite", "software", "system", "systems", "tool", "tools",
        "app", "certified", "certification", "cpa", "acca", "cfa", "erp", "crm", "sql",
        "python", "java", "javascript", "typescript", "react", "vue", "angular", "node",
        "git", "docker", "figma", "jira", "computerized", "computerised", "tableau",
        "power bi", "pos", "photoshop", "illustrator", "sage", "peachtree", "odoo",
        "linux", "windows", "macos", "hardware", "printer", "printers", "network", "networking",
        "troubleshoot", "troubleshooting", "helpdesk", "desktop support", "tier 1", "tier 2",
        "active directory", "salesforce", "hubspot", "aws", "azure", "gcp", "fastapi", "django",
    ]
    if cat in ("certification", "hard_skill") or _has_kw(combined, tool_indicators):
        return "tools"

    # 4. Domain Knowledge & Functional Competencies (default)
    return "domain"


def _generate_action_recommendation(
    req: Requirement,
    verdict: Verdict,
    potential_gain: float,
) -> str:
    skill_label = req.normalized_skill or req.text
    if len(skill_label) > 60:
        skill_label = skill_label[:57].rstrip() + "..."

    combined_text = f"{req.text} {req.normalized_skill or ''}".lower()

    # Handle boilerplate / eligibility criteria cleanly
    if _is_boilerplate_or_eligibility(combined_text):
        rec = "Add a dedicated projects or academic coursework section demonstrating foundational practical skills in your core field."
        return f"+{potential_gain}% Match Boost: {rec} ({req.priority.capitalize()})"

    category_type = _classify_action_category(req)

    # ── Strategy 1: Experience & Tenures ─────────────────────────────────────
    if category_type == "experience":
        if _has_kw(combined_text, ["intern", "internship"]):
            rec = "Add previous internship or work entries covering relevant roles, or highlight student consulting and volunteer experience."
        else:
            rec = f"Add previous internship or work entries covering '{skill_label}', or highlight relevant student consulting / volunteer roles."

    # ── Strategy 2: Soft Skills & Behavioral Traits ──────────────────────────
    elif category_type == "soft_skills":
        if _has_kw(combined_text, ["banking", "bank", "financial environment", "fintech"]):
            rec = f"Highlight experience or self-study with banking software, fintech workflows, or financial data compliance standards for '{skill_label}'."
        elif _has_kw(combined_text, ["detail", "accuracy", "error", "commit", "precision", "quality"]):
            rec = "Quantify this trait in your existing bullets (e.g., audited records with 0% error rate, completed quality control steps)."
        elif _has_kw(combined_text, ["learn", "desire", "growth", "curiosity", "adapt", "adaptability", "fast learner"]):
            rec = "Quantify this trait in your existing bullets (e.g., completed self-paced learning modules, self-directed certifications within 30 days)."
        elif _has_kw(combined_text, ["communicat", "teamwork", "interpersonal", "collaborat"]):
            rec = "Quantify cross-functional impact in your bullets (e.g., partnered with 3+ departments, presented findings to leadership)."
        elif _has_kw(combined_text, ["problem", "solving", "analytical", "critical thinking"]):
            rec = "Frame this with the STAR method (Situation, Task, Action, Result) showcasing root-cause troubleshooting and measurable resolution outcomes."
        elif _has_kw(combined_text, ["leader", "time management", "multitask", "organiz"]):
            rec = "Highlight ownership in your bullets (e.g., prioritized competing deadlines, led project milestones, mentored peers)."
        else:
            rec = "Quantify this trait in your existing bullets (e.g., audit error reduction rates, quality control steps, or self-directed coursework)."

    # ── Strategy 3 & 4: Tools, Hard Skills & Domain Knowledge ────────────────
    # A. IT, Systems, Networking & Desktop Support
    elif _has_kw(combined_text, ["troubleshoot", "troubleshooting", "helpdesk", "tier-1", "tier-2", "tier 1", "tier 2", "it support", "technical support", "user support"]):
        rec = f"Quantify ticket volume (e.g., 40+ tickets/wk via Jira / ServiceNow), Tier-1/2 resolution rates (e.g., 95% FCR), and protocols diagnosed (TCP/IP, Wi-Fi, VPN, DNS) for '{skill_label}'."
    elif _has_kw(combined_text, ["printer", "printers", "hardware", "workstation", "workstations", "windows os", "windows 10", "windows 11", "desktop support", "desktop rollout", "rollout", "office software", "computer hardware"]):
        rec = f"Detail configuration, rollout, or lab setup of Windows 10/11 workstations, network printers, and Microsoft 365 / office applications for '{skill_label}'."
    elif _has_kw(combined_text, ["active directory", "ad ds", "gpo", "group policy", "hyper-v", "virtualbox", "sysadmin", "system admin"]):
        rec = "Highlight Active Directory user provisioning, Group Policy (GPO) security enforcement, and VM environments (Hyper-V / VirtualBox)."
    elif _has_kw(combined_text, ["documentation", "document technical", "sop", "sops", "knowledge base", "runbook", "technical writing"]):
        rec = "Mention authored Standard Operating Procedures (SOPs), Knowledge Base (KB) articles, or user onboarding workflows (e.g., printer mapping, setup guides)."
    elif _has_kw(combined_text, ["network", "networking", "cisco", "tcp/ip", "subnet", "vpn", "firewall", "dns", "dhcp"]):
        rec = f"List specific hands-on networking tasks performed for '{skill_label}' (e.g., TCP/IP configuration, VLAN/subnetting, VPN setup, or router diagnostics)."

    # B. Software Engineering, Web & Cloud/DevOps
    elif _has_kw(combined_text, ["react", "vue", "angular", "next.js", "frontend", "front-end", "html", "css", "tailwind", "javascript", "typescript"]):
        rec = f"Detail component architecture, responsive UI design, state management, and modern framework implementation in '{skill_label}'."
    elif _has_kw(combined_text, ["python", "java", "node", "nodejs", "fastapi", "django", "express", "backend", "back-end", "rest api", "restful", "graphql", "microservices"]):
        rec = f"Highlight API design, authentication (JWT/OAuth), database integration, and automated test coverage in '{skill_label}'."
    elif _has_kw(combined_text, ["sql", "mysql", "postgresql", "mongodb", "redis", "database", "query optimization"]):
        rec = f"List specific SQL queries or database schemas designed in '{skill_label}' (e.g., indexing, complex JOINs, query optimization)."
    elif _has_kw(combined_text, ["docker", "kubernetes", "aws", "azure", "gcp", "ci/cd", "devops", "cloud"]):
        rec = f"List specific cloud infrastructure or containerization tasks performed for '{skill_label}' (e.g., Dockerfiles, CI/CD pipelines, cloud deployment)."
    elif _has_kw(combined_text, ["git", "github", "gitlab", "version control", "agile", "scrum"]):
        rec = "Detail version control workflows (e.g., pull requests, branching strategies, code reviews) and agile sprint participation."

    # C. Data Science, Analytics & AI
    elif _has_kw(combined_text, ["tableau", "power bi", "dashboard", "data analysis", "data visualization", "business intelligence", "looker"]):
        rec = f"Cite specific interactive dashboards built in '{skill_label}' with measurable business metrics and automated data refreshes."
    elif _has_kw(combined_text, ["machine learning", "deep learning", "nlp", "pytorch", "tensorflow", "scikit-learn", "data science"]):
        rec = f"Detail model training/evaluation pipelines, performance metrics (accuracy, F1, latency), and data preprocessing in '{skill_label}'."

    # D. Accounting, Finance & Banking
    elif _has_kw(combined_text, ["quickbooks", "accounting system", "ledger", "bookkeeping", "xero", "sage", "peachtree", "odoo"]):
        rec = f"List specific {skill_label} tasks performed (e.g., ledger entries, invoice reconciliation) or add relevant software certification."
    elif _has_kw(combined_text, ["excel", "spreadsheet"]):
        rec = f"List specific {skill_label} tasks performed (e.g., pivot tables, VLOOKUP/XLOOKUP, formulas) or add relevant software certification."
    elif _has_kw(combined_text, ["sap", "erp"]):
        rec = f"List specific {skill_label} modules used (e.g., AP/AR, general ledger) or add relevant system certification."
    elif _has_kw(combined_text, ["tax", "taxation", "vat", "withholding"]):
        rec = "Mention specific coursework or self-study in local tax laws (e.g., monthly VAT returns, withholding tax basics)."
    elif _has_kw(combined_text, ["banking", "bank", "financial environment", "fintech"]):
        rec = f"Highlight experience or self-study with banking software, fintech workflows, or financial data compliance standards for '{skill_label}'."
    elif _has_kw(combined_text, ["financial modeling", "dcf", "valuation", "budgeting", "forecasting"]):
        rec = f"Detail financial models built for '{skill_label}' (e.g., 3-statement models, DCF valuation, variance analysis)."
    elif _has_kw(combined_text, ["standard", "gaap", "ifrs", "audit", "compliance", "regulation", "internal control"]):
        rec = f"Cite specific coursework modules, accounting standards (e.g., IFRS/GAAP), or compliance case studies analyzed for '{skill_label}'."

    # E. Sales, Marketing, Design & Communications
    elif _has_kw(combined_text, ["seo", "sem", "google ads", "meta ads", "digital marketing", "campaign", "roas"]):
        rec = f"Quantify campaign metrics in '{skill_label}' (e.g., conversion rate increases, ROAS, organic search traffic growth)."
    elif _has_kw(combined_text, ["sales", "cold call", "prospecting", "b2b", "lead generation", "salesforce", "hubspot", "crm"]):
        rec = f"Quantify sales pipeline achievements (e.g., quota attainment %, outbound lead volume, CRM pipeline tracking) for '{skill_label}'."
    elif _has_kw(combined_text, ["figma", "ui/ux", "photoshop", "illustrator", "graphic design", "branding"]):
        rec = f"Highlight specific design artifacts produced in '{skill_label}' (e.g., responsive prototypes, brand identity kits, marketing collateral)."
    elif _has_kw(combined_text, ["social media", "copywriting", "content creation", "content writing"]):
        rec = f"Cite audience growth %, engagement rate improvements, and published content campaigns for '{skill_label}'."

    # F. Human Resources, Administration & Operations
    elif _has_kw(combined_text, ["recruitment", "recruiting", "talent acquisition", "onboarding", "payroll", "human resources", "hr"]):
        rec = f"Detail HR workflows managed for '{skill_label}' (e.g., candidate pipeline sourcing, onboarding SOPs, payroll processing, labor compliance)."
    elif _has_kw(combined_text, ["administrative", "admin", "office management", "executive assistant", "filing", "calendar"]):
        rec = f"Highlight administrative tasks managed for '{skill_label}' (e.g., executive schedule coordination, meeting minutes, vendor procurement)."
    elif _has_kw(combined_text, ["supply chain", "logistics", "inventory", "procurement", "warehouse"]):
        rec = f"Detail operational metrics for '{skill_label}' (e.g., inventory accuracy %, order fulfillment cycle time, vendor cost reductions)."
    elif _has_kw(combined_text, ["customer service", "customer support", "client support", "call center", "csat"]):
        rec = f"Quantify customer service achievements (e.g., 95%+ CSAT, daily inquiry resolution volume, ticket escalation turnaround) for '{skill_label}'."

    # ── Fallback for Tools / Certifications ──────────────────────────────────
    elif category_type == "tools":
        if _has_kw(combined_text, ["certif"]) or req.category == "certification":
            rec = f"List completed {skill_label} credentials, exam progress, or relevant specialized coursework labs."
        else:
            rec = f"List specific practical tasks performed with '{skill_label}' (e.g., core workflows, module usage) or add relevant software certification."

    # ── Fallback for Domain / Education / Languages ──────────────────────────
    else:
        if req.category == "education" or _has_kw(combined_text, ["degree", "major", "bachelor", "diploma"]):
            rec = f"Highlight relevant academic degree coursework, academic honors, or specialized modules in '{skill_label}'."
        elif req.category == "language" or _has_kw(combined_text, ["english", "khmer", "language", "chinese", "french"]):
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

    action_candidates: list[tuple[float, bool, str]] = []

    for res in results:
        req = req_map.get(res.requirement_id)
        if not req or res.verdict == "proven":
            continue

        is_boilerplate = _is_boilerplate_or_eligibility(f"{req.text} {req.normalized_skill or ''}")

        weight = 1.0 if req.priority == "required" else 0.4
        current_score = verdict_scores.get(res.verdict, 0.0)
        # Potential gain if upgraded to proven (1.0)
        potential_gain = round(((1.0 - current_score) * weight / total_weight) * 100.0, 1)

        action_text = _generate_action_recommendation(req, res.verdict, potential_gain)
        # Non-boilerplate actions prioritized over boilerplate/eligibility notices
        action_candidates.append((potential_gain, not is_boilerplate, action_text))

    # Sort descending: actionable items first, then by % boost
    action_candidates.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return [action for _, _, action in action_candidates[:5]]


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

