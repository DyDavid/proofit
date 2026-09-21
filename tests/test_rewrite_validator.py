"""30-Case Adversarial Suite for F5 Hallucination Validator.

Evaluates precision and recall of the validator across multiple failure modes:
1. Magnitude Inflation (3 -> 300 users)
2. Duration Inflation (3 months -> 2 years)
3. Scope / Title Inflation (Project -> Employed Senior Engineer)
4. Tool / Skill Insertion (Invented Kubernetes/AWS)
5. Outcome / Metric Invention (Invented 50% revenue growth)
6. Leadership / Role Inflation (Solo -> Managed team of 5)
7. Date / Year Fabrication (2020 -> 2026)
8. Legitimate evidence-bound rephrasings (Must Pass)
"""

from __future__ import annotations

import pytest

from engine.normalize.schema import Evidence
from engine.rewrite.validator import validate_rewrite


@pytest.fixture
def base_evidence_project() -> Evidence:
    return Evidence(
        id="e1",
        source_line="Built a Delivery Tracker using Vue.js and Node.js (3 months academic project, team of 2).",
        evidence_type="project",
        skills=["Vue.js", "Node.js", "JavaScript"],
        duration_months=3,
        team_size=2,
    )


@pytest.fixture
def base_evidence_intern() -> Evidence:
    return Evidence(
        id="e2",
        source_line="Intern Web Developer at KhmerTech (6 months, 2023): Developed Vue.js frontend interfaces.",
        evidence_type="internship",
        skills=["Vue.js", "HTML", "CSS"],
        duration_months=6,
    )


# 30 Adversarial Test Cases: (phrasing, is_employment, expected_ok, category)
ADVERSARIAL_CASES = [
    # --- Category 1: Magnitude Inflation ---
    ("Built a Delivery Tracker scaling to 300 active users using Vue.js.", False, False, "magnitude"),
    ("Processed 5000 requests per second using Node.js.", False, False, "magnitude"),
    ("Built a system used by 50 enterprise clients.", False, False, "magnitude"),

    # --- Category 2: Duration Inflation ---
    ("2 years of experience building Delivery Tracker with Vue.js.", False, False, "duration"),
    ("Spent 12 months optimizing Node.js backend performance.", False, False, "duration"),
    ("Worked for 5 years on web development projects.", False, False, "duration"),

    # --- Category 3: Scope & Title Inflation (forbidden.json) ---
    ("Employed as Lead Developer at KhmerTech.", False, False, "scope"),
    ("Worked as Senior Software Engineer at Delivery Tracker.", False, False, "scope"),
    ("Full-time employee and Manager at KhmerTech.", False, False, "scope"),
    ("5 years of professional experience in frontend development.", False, False, "scope"),

    # --- Category 4: Tool / Skill Insertion ---
    ("Built a Delivery Tracker using Vue.js, Node.js, and Kubernetes.", False, False, "tool"),
    ("Deployed Delivery Tracker on AWS EC2 and Terraform.", False, False, "tool"),
    ("Utilized Python, Django, and PostgreSQL for Delivery Tracker.", False, False, "tool"),
    ("Configured Docker containers and CI/CD pipelines.", False, False, "tool"),

    # --- Category 5: Outcome / Metric Invention ---
    ("Increased system speed by 80% through code optimization.", False, False, "outcome"),
    ("Generated $50,000 in revenue for KhmerTech.", True, False, "outcome"),
    ("Reduced infrastructure cost by 40%.", True, False, "outcome"),
    ("Boosted user retention by 25%.", False, False, "outcome"),

    # --- Category 6: Leadership / Role Inflation ---
    ("Managed a team of 10 developers to build Delivery Tracker.", False, False, "leadership"),
    ("Led engineering department at KhmerTech.", True, False, "leadership"),
    ("Supervised 5 junior developers.", False, False, "leadership"),

    # --- Category 7: Date / Year Fabrication ---
    ("Built Delivery Tracker in 2026.", False, False, "date"),
    ("Worked at KhmerTech from 2018 to 2022.", True, False, "date"),

    # --- Category 8: Legitimate Rephrasings (MUST PASS) ---
    ("Developed frontend interfaces with Vue.js during 6-month internship at KhmerTech.", True, True, "legitimate"),
    ("Constructed web delivery tracking system using Node.js and Vue.js in a team of 2.", False, True, "legitimate"),
    ("Created interactive Vue.js user interfaces for KhmerTech.", True, True, "legitimate"),
    ("Built a web delivery application utilizing JavaScript, Vue.js, and Node.js.", False, True, "legitimate"),
    ("Participated in a 3-month project developing a delivery tracker using Vue.js.", False, True, "legitimate"),
    ("Assisted with Vue.js frontend development at KhmerTech.", True, True, "legitimate"),
    ("Engineered a delivery tracking application using Vue.js frontend and Node.js backend.", False, True, "legitimate"),
]


@pytest.mark.parametrize("phrasing, is_intern, expected_ok, category", ADVERSARIAL_CASES)
def test_adversarial_validator(
    phrasing: str,
    is_intern: bool,
    expected_ok: bool,
    category: str,
    base_evidence_project: Evidence,
    base_evidence_intern: Evidence,
) -> None:
    ev = base_evidence_intern if is_intern else base_evidence_project
    res = validate_rewrite(suggested_phrasing=phrasing, evidence_records=[ev], use_llm=False)
    assert res.ok == expected_ok, f"Failed case [{category}]: '{phrasing}' expected ok={expected_ok}, got {res.ok}. Violations: {res.violations}"


def test_validator_precision_recall_summary(
    base_evidence_project: Evidence,
    base_evidence_intern: Evidence,
) -> None:
    tp = fp = tn = fn = 0
    for phrasing, is_intern, expected_ok, _ in ADVERSARIAL_CASES:
        ev = base_evidence_intern if is_intern else base_evidence_project
        res = validate_rewrite(suggested_phrasing=phrasing, evidence_records=[ev], use_llm=False)
        actual_ok = res.ok
        if expected_ok and actual_ok:
            tp += 1
        elif not expected_ok and not actual_ok:
            tn += 1
        elif not expected_ok and actual_ok:
            fp += 1
        elif expected_ok and not actual_ok:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    assert precision >= 0.9, f"Precision target >= 90%, got {precision:.2f}"
    assert recall >= 0.85, f"Recall target >= 85%, got {recall:.2f}"
