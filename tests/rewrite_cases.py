"""The labelled adversarial + legitimate dataset for
`engine.rewrite.validate.validate_rewrite` (Phase 4 hardening task 2).

30 cases: 20 adversarial across the six categories PERSON_B_PLAN_v2.md's
report table names (magnitude inflation, duration inflation, status upgrade,
tool insertion, outcome invention, subtle paraphrase), and 10 legitimate
rephrasings that must pass all three layers.

Every case's `caught_by` was verified empirically, not assumed: each one was
run against `precheck_scope_inflation` and `precheck_rewrite` directly (no
mocking) before being written here, and the layer that actually produced a
`ValidationResult(ok=False, ...)` — or, for the `llm` cases, the fact that
*both* deterministic layers returned `None` — is what is recorded. A case
mislabelled `precheck` that the scope gate actually catches would make the
project's precision/recall table wrong, so this file is the single source of
truth both the test suite and `scripts/validator_metrics.py` read from.

Design notes specific to certain categories:

- **status upgrade** cases are labelled `scope`, not `precheck`, because
  `precheck_scope_inflation` runs first in `validate_rewrite` and returns
  immediately once it fires — `precheck_rewrite` never runs on these at all.
- **duration inflation** cases override `source_line` (not just
  `duration_months`) to a matching sentence. Overriding only the field and
  not the prose would leave the *old* sentence's digits (e.g. the shared
  fixture's "2 teammates") sitting in the haystack, and an inflated duration
  that happens to reuse one of those leftover digits would silently slip
  past the pre-check — a false pass, not a real one.
- **outcome invention** and **subtle paraphrase** cases are labelled `llm`
  because they were confirmed to introduce no new number, no acronym, no
  sentence-non-initial capitalized word, and no forbidden phrase — so both
  deterministic layers return `None` on them by construction, and only a
  semantic read (the mocked LLM layer, standing in for the real one) can
  reject them. This is the empirical proof, not a restatement of the design
  intent, that the LLM layer is load-bearing rather than decorative.
- Three of the ten legitimate cases (`legit-emp-1..3`) cite an `employment`,
  `internship` or `part_time` record while using professional language
  ("worked professionally", "employed part-time as..."). These prove the
  Task 1 scope gate's all-cited-are-non-employment condition holds: the gate
  stays silent on all three, deferring to the LLM, exactly as designed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ValidatorCase:
    id: str
    category: str
    suggested_phrasing: str
    evidence_overrides: dict[str, object] = field(default_factory=dict)
    should_reject: bool = True
    caught_by: Literal["scope", "precheck", "llm", "none"] = "none"


# Reused by tests/test_rewrite_validator.py's `_evidence()` helper: a
# 3-month, 2-person Python course project, matching the module this dataset
# replaces. Duration-inflation cases override this wholesale (see module
# docstring above for why).
BASE_SOURCE_LINE = (
    "Built a Python-based encryption tool for a university course project, "
    "coordinating with 2 teammates over 3 months."
)

_DUR_SOURCE_LINE = (
    "Built a Python-based encryption tool for a university course project, "
    "coordinating with 3 teammates over 4 months."
)

CASES: list[ValidatorCase] = [
    # ── magnitude inflation (3 → 30): precheck ──────────────────────────
    ValidatorCase(
        id="mag-1",
        category="magnitude_inflation",
        # Inflates a real outcome percentage 3% -> 30%.
        suggested_phrasing=(
            "Reduced encryption benchmark runtime by 30%, cutting processing "
            "overhead significantly."
        ),
        evidence_overrides={"outcome": "Reduced encryption benchmark runtime by 3%."},
        caught_by="precheck",
    ),
    ValidatorCase(
        id="mag-2",
        category="magnitude_inflation",
        # Inflates team_size=2 to a claimed headcount of 20.
        suggested_phrasing=(
            "Led a team of 20 student developers to build the Python-based "
            "encryption tool."
        ),
        evidence_overrides={"team_size": 2},
        caught_by="precheck",
    ),
    ValidatorCase(
        id="mag-3",
        category="magnitude_inflation",
        # Inflates a real dataset count 3 -> 30.
        suggested_phrasing=(
            "Processed 30 sample datasets while testing the Python-based "
            "encryption tool."
        ),
        evidence_overrides={
            "outcome": "Processed 3 sample datasets while testing the tool."
        },
        caught_by="precheck",
    ),
    ValidatorCase(
        id="mag-4",
        category="magnitude_inflation",
        # Inflates a real testing-round count 3 -> 30.
        suggested_phrasing=(
            "Ran 30 rounds of validation testing on the Python-based encryption "
            "tool before submission."
        ),
        evidence_overrides={
            "outcome": "Ran 3 rounds of validation testing on the tool before submission."
        },
        caught_by="precheck",
    ),
    # ── duration inflation (4 months → 2 years): precheck ───────────────
    ValidatorCase(
        id="dur-1",
        category="duration_inflation",
        # 4 months restated as 2 years; source_line rewritten so no stray digit survives.
        suggested_phrasing=(
            "Spent 2 years building a Python-based encryption tool for a "
            "university course project."
        ),
        evidence_overrides={
            "source_line": _DUR_SOURCE_LINE,
            "duration_months": 4,
            "team_size": 3,
        },
        caught_by="precheck",
    ),
    ValidatorCase(
        id="dur-2",
        category="duration_inflation",
        # 4 months restated as 24 months.
        suggested_phrasing=(
            "Worked on the Python-based encryption tool over 24 months as a "
            "university course project."
        ),
        evidence_overrides={
            "source_line": _DUR_SOURCE_LINE,
            "duration_months": 4,
            "team_size": 3,
        },
        caught_by="precheck",
    ),
    ValidatorCase(
        id="dur-3",
        category="duration_inflation",
        # 4 months restated as 18 months.
        suggested_phrasing=(
            "Developed the Python-based encryption tool across 18 months of "
            "university coursework."
        ),
        evidence_overrides={
            "source_line": _DUR_SOURCE_LINE,
            "duration_months": 4,
            "team_size": 3,
        },
        caught_by="precheck",
    ),
    # ── status upgrade (project → job): scope ───────────────────────────
    ValidatorCase(
        id="status-1",
        category="status_upgrade",
        # Forbidden phrase "professional" on a project record.
        suggested_phrasing=(
            "Worked professionally as a software engineer, delivering "
            "production features independently."
        ),
        evidence_overrides={"evidence_type": "project"},
        caught_by="scope",
    ),
    ValidatorCase(
        id="status-2",
        category="status_upgrade",
        # Forbidden phrase "employed" on a coursework record.
        suggested_phrasing=(
            "Was employed as a software developer to build the encryption "
            "tool for the course."
        ),
        evidence_overrides={
            "evidence_type": "coursework",
            "source_line": (
                "Completed a semester-long coursework assignment building a "
                "Python-based encryption tool, coordinating with 2 classmates "
                "over 3 months."
            ),
        },
        caught_by="scope",
    ),
    ValidatorCase(
        id="status-3",
        category="status_upgrade",
        # Forbidden phrase "worked at" on a competition record.
        suggested_phrasing=(
            "Worked at a cybersecurity firm building the encryption tool "
            "during the competition."
        ),
        evidence_overrides={
            "evidence_type": "competition",
            "source_line": (
                "Built a Python-based encryption tool for a university "
                "hackathon competition, coordinating with 2 teammates over 3 "
                "months."
            ),
        },
        caught_by="scope",
    ),
    ValidatorCase(
        id="status-4",
        category="status_upgrade",
        # Forbidden phrase "engineer at" on a volunteer record.
        suggested_phrasing=(
            "Served as a software engineer at the nonprofit, building the "
            "encryption tool independently."
        ),
        evidence_overrides={
            "evidence_type": "volunteer",
            "source_line": (
                "Built a Python-based encryption tool as a volunteer for a "
                "community nonprofit, coordinating with 2 other volunteers "
                "over 3 months."
            ),
        },
        caught_by="scope",
    ),
    # ── tool insertion: precheck ─────────────────────────────────────────
    ValidatorCase(
        id="tool-1",
        category="tool_insertion",
        # Invents "Docker", never in evidence.skills.
        suggested_phrasing=(
            "Containerized the Python-based encryption tool with Docker for "
            "deployment."
        ),
        evidence_overrides={"skills": ["Python"]},
        caught_by="precheck",
    ),
    ValidatorCase(
        id="tool-2",
        category="tool_insertion",
        # Invents "AWS" (an acronym, checked at any sentence position).
        suggested_phrasing=(
            "Deployed the Python-based encryption tool on AWS infrastructure "
            "for the course project."
        ),
        evidence_overrides={"skills": ["Python"]},
        caught_by="precheck",
    ),
    ValidatorCase(
        id="tool-3",
        category="tool_insertion",
        # Invents "React", never in evidence.skills.
        suggested_phrasing=(
            "Built a React dashboard to visualize metrics for the Python "
            "cryptography tool."
        ),
        evidence_overrides={"skills": ["Python", "cryptography"]},
        caught_by="precheck",
    ),
    # ── outcome invention: llm (introduces no new number/noun/phrase) ───
    ValidatorCase(
        id="outcome-1",
        category="outcome_invention",
        # Invents institutional adoption never in evidence.outcome.
        suggested_phrasing=(
            "Built a Python-based encryption tool for a university course "
            "project, which the department later adopted for its "
            "introductory security curriculum."
        ),
        caught_by="llm",
    ),
    ValidatorCase(
        id="outcome-2",
        category="outcome_invention",
        # Invents a production deployment never in evidence.outcome.
        suggested_phrasing=(
            "Built a Python-based encryption tool for a university course "
            "project, and the resulting prototype was later deployed to "
            "production servers."
        ),
        caught_by="llm",
    ),
    ValidatorCase(
        id="outcome-3",
        category="outcome_invention",
        # Invents a "top submission" recognition never in evidence.outcome.
        suggested_phrasing=(
            "Built a Python-based encryption tool for a university course "
            "project, earning recognition as the top submission that "
            "semester."
        ),
        caught_by="llm",
    ),
    # ── subtle paraphrase ("participated" → "led"): llm ──────────────────
    ValidatorCase(
        id="paraphrase-1",
        category="subtle_paraphrase",
        # "coordinating with" upgraded to sole "Led", no new token.
        suggested_phrasing=(
            "Led the university course project, building a Python-based "
            "encryption tool over 3 months with 2 teammates."
        ),
        caught_by="llm",
    ),
    ValidatorCase(
        id="paraphrase-2",
        category="subtle_paraphrase",
        # "coordinating with 2 teammates" erased into solo "Independently architected".
        suggested_phrasing=(
            "Independently architected a Python-based encryption tool for a "
            "university course project."
        ),
        caught_by="llm",
    ),
    ValidatorCase(
        id="paraphrase-3",
        category="subtle_paraphrase",
        # "coordinating with" upgraded to "Spearheaded", no new token.
        suggested_phrasing=(
            "Spearheaded the university course project that built a "
            "Python-based encryption tool with 2 teammates over 3 months."
        ),
        caught_by="llm",
    ),
    # ── legitimate: must pass all three layers ───────────────────────────
    ValidatorCase(
        id="legit-1",
        category="legitimate",
        # Reordered rephrasing of the same facts.
        suggested_phrasing=(
            "Coordinated with 2 teammates over 3 months to build a "
            "Python-based encryption tool for a university course project."
        ),
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-2",
        category="legitimate",
        # JD-vocabulary substitution ("cryptography" already in evidence.skills).
        suggested_phrasing=(
            "Implemented a Python cryptography tool for a university course "
            "project."
        ),
        evidence_overrides={"skills": ["Python", "cryptography"]},
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-3",
        category="legitimate",
        # Condensed rephrasing, no new claims.
        suggested_phrasing="Built a Python encryption tool as a university course project.",
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-4",
        category="legitimate",
        # Passive-voice rephrasing of the same facts.
        suggested_phrasing=(
            "A Python-based encryption tool was built for a university "
            "course project by a team of 2 over 3 months."
        ),
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-5",
        category="legitimate",
        # Synonym substitution: "coordinating" -> "Collaborated".
        suggested_phrasing=(
            "Collaborated with 2 teammates over 3 months to build a "
            "Python-based encryption tool for a university course project."
        ),
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-6",
        category="legitimate",
        # Skill-forward rephrasing, same facts, same headcount and duration.
        suggested_phrasing=(
            "Applied Python to build an encryption tool as part of a "
            "university course project, working alongside 2 teammates for 3 "
            "months."
        ),
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-7",
        category="legitimate",
        # Cites a real (not invented) evidence.outcome verbatim.
        suggested_phrasing=(
            "Built a Python-based encryption tool for a university course "
            "project, earning a top grade in the course."
        ),
        evidence_overrides={"outcome": "Received a top grade in the course."},
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-emp-1",
        category="legitimate",
        # Professional language on a genuine `employment` record: the scope
        # gate must stay silent (a cited employment record is present).
        suggested_phrasing=(
            "Worked professionally as a software engineer, building a "
            "Python-based encryption tool over 3 months with 2 teammates."
        ),
        evidence_overrides={
            "evidence_type": "employment",
            "source_line": (
                "Worked as a backend engineer at a fintech startup for 3 "
                "months, coordinating with 2 teammates to build a "
                "Python-based encryption tool."
            ),
        },
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-emp-2",
        category="legitimate",
        # "professional" + "engineer at" on a genuine `internship` record.
        suggested_phrasing=(
            "Worked as a professional engineer at the company, building a "
            "Python-based encryption tool during the internship."
        ),
        evidence_overrides={
            "evidence_type": "internship",
            "source_line": (
                "Interned as a software engineer for 3 months, coordinating "
                "with 2 teammates to build a Python-based encryption tool."
            ),
        },
        should_reject=False,
    ),
    ValidatorCase(
        id="legit-emp-3",
        category="legitimate",
        # "employed" on a genuine `part_time` record.
        suggested_phrasing=(
            "Was formally employed part-time as a support engineer, building "
            "a Python-based encryption tool over 3 months with 2 teammates."
        ),
        evidence_overrides={
            "evidence_type": "part_time",
            "source_line": (
                "Worked part-time as a support engineer for 3 months, "
                "coordinating with 2 teammates to build a Python-based "
                "encryption tool."
            ),
        },
        should_reject=False,
    ),
]

__all__ = ["ValidatorCase", "BASE_SOURCE_LINE", "CASES"]
