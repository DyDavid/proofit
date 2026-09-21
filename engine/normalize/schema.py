"""The one schema.

Both a job description and a resume normalize into models defined here, and the
match engine compares *schema against schema* — never text against text. That is
the architecture story for the defence; do not deviate from it.
(PROJECT_SPEC.md §6.)

------------------------------------------------------------------------------
PROVISIONAL — OWNED BY PERSON A
------------------------------------------------------------------------------
PERSON_B_PLAN_v2.md §2 assigns ``engine/normalize/`` to Person A, who publishes
the real ``schema.py`` at Checkpoint 1 (end of Week 3). This file was written by
Person B from PROJECT_SPEC.md §8 so that Phase 1 (generated TypeScript types,
golden fixtures, mock-mode API, shell screens) is not blocked waiting on it.

At CP1, Person A's version replaces this file wholesale. The staleness check in
``.github/workflows/ci.yml`` fails the build if ``web/lib/types.ts`` no longer
matches, so drift is caught immediately rather than at demo time.

Person B has pre-added the four fields PERSON_B_PLAN_v2.md §5 Phase 1.1 says to
negotiate at CP1. Each is marked ``# CP1:`` below. If Person A rejects one, delete
it here and regenerate the types — do not paper over it in the UI.
------------------------------------------------------------------------------

Non-negotiable rules from PROJECT_SPEC.md §9 that are enforced *in code* here,
because the examiner will test them:

    Rule 3 — Every verdict is traceable.
             ``MatchResult`` cannot exist without either a non-empty
             ``evidence_ids`` list or an explicit ``missing_reason``.

    Rule 2 — No scope inflation.
             Non-employment evidence (coursework, project, competition,
             volunteer) can never produce a ``proven`` verdict on an
             ``experience`` requirement. Checked on ``Match`` whenever the
             embedded job and resume are present.

Both rules raise ``ValidationError`` at parse time, so a violation cannot reach
the database, the API response, or the screen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "SCHEMA_VERSION",
    "SourceType",
    "Seniority",
    "SponsorsVisa",
    "RequirementCategory",
    "RequirementPriority",
    "EvidenceType",
    "Verdict",
    "RealismVerdict",
    "AnalysisStatus",
    "MatchStage",
    "Requirement",
    "Job",
    "Education",
    "Evidence",
    "Resume",
    "MatchResult",
    "HiddenStrength",
    "PriorityAction",
    "Match",
    "BaselineResult",
    "BaselineMatch",
    "SchemaBundle",
    "NON_EMPLOYMENT_EVIDENCE",
    "VERDICT_DISPLAY_ORDER",
    "PRIORITY_DISPLAY_ORDER",
    "utcnow",
]

#: Bumped whenever a field is added, removed or retyped. Stored on every Match so
#: the evaluation chapter (Phase 6) can state exactly which schema produced a row.
SCHEMA_VERSION = "0.1.0-provisional"


def utcnow() -> datetime:
    """Timezone-aware UTC now. Never use naive datetimes — Supabase stores tz-aware."""
    return datetime.now(UTC)


# ── Literal aliases ───────────────────────────────────────────────────────────
# Literals rather than enum.Enum: they serialise to plain strings in JSON, survive
# the round-trip to TypeScript as string-union types, and keep fixtures readable.

SourceType = Literal["scraped", "pasted"]
Seniority = Literal["intern", "entry", "junior", "mid", "senior"]
SponsorsVisa = Literal["yes", "no", "unstated"]

RequirementCategory = Literal[
    "hard_skill",
    "soft_skill",
    "education",
    "certification",
    "experience",
    "language",
    "other",
]
RequirementPriority = Literal["required", "preferred"]

EvidenceType = Literal[
    "employment",
    "internship",
    "part_time",
    "coursework",
    "project",
    "volunteer",
    "certification",
    "competition",
]

Verdict = Literal["proven", "partial", "missing"]
RealismVerdict = Literal["strong_fit", "stretch", "unrealistic"]

#: Lifecycle of one analysis job. Owned by the API, but declared here so that the
#: engine, the API and the generated TypeScript all agree on the spelling.
AnalysisStatus = Literal["queued", "running", "done", "failed"]

#: Drives the progress stepper (PERSON_B_PLAN_v2.md §5 Phase 2.3). ``run_match``
#: should emit these through a progress hook; the UI falls back to timed fake
#: stages when ``stage`` is null.
MatchStage = Literal[
    "reading_resume",
    "reading_job",
    "matching_requirements",
    "checking_realism",
]

#: Evidence that is *not* paid professional employment. PROJECT_SPEC.md §9 rule 2
#: and F4: these may support a ``partial`` verdict on an experience requirement,
#: never a ``proven`` one. Enforced by ``Match._enforce_no_scope_inflation``.
NON_EMPLOYMENT_EVIDENCE: frozenset[str] = frozenset(
    {"coursework", "project", "volunteer", "competition"}
)

#: The results list is grouped gaps-first — that is what the user can act on.
VERDICT_DISPLAY_ORDER: tuple[Verdict, ...] = ("missing", "partial", "proven")
PRIORITY_DISPLAY_ORDER: tuple[RequirementPriority, ...] = ("required", "preferred")


class _Base(BaseModel):
    """Shared config.

    ``extra="forbid"`` is deliberate: a typo in a hand-written fixture, or a field
    Person A renames at CP1, fails loudly here instead of silently rendering as
    ``undefined`` in the browser.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Job ───────────────────────────────────────────────────────────────────────


class Requirement(_Base):
    """One requirement, extracted verbatim from the job post.

    One record per requirement — never a bundled sentence. ``text`` is quoted back
    to the user on the results screen, so it must be the JD's own words.
    """

    id: str = Field(
        ...,
        pattern=r"^r\d+$",
        description="Stable within one job: r1, r2, … Referenced by MatchResult.requirement_id.",
        examples=["r1"],
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Verbatim requirement from the JD. Shown in English regardless of UI locale.",
    )
    category: RequirementCategory
    priority: RequirementPriority = Field(
        ...,
        description="From JD wording: 'must have' → required, 'nice to have' → preferred.",
    )
    normalized_skill: str | None = Field(
        default=None,
        description="Canonical skill name, e.g. 'React'. None when the requirement names no single skill.",
    )
    # CP1: requested by Person B — the results list renders Missing → Partial →
    # Proven, so the JD's original ordering is otherwise lost. Needed to show
    # requirements in source order inside each verdict group.
    display_order: int | None = Field(
        default=None,
        ge=0,
        description="Zero-based position in the original JD. None if the normalizer did not record it.",
    )


class Job(_Base):
    """A normalized job description, from any source: paste, URL or scraper."""

    source_url: str | None = None
    source_type: SourceType
    content_hash: str = Field(
        ...,
        min_length=8,
        description=(
            "Hash of the raw JD text. PROJECT_SPEC.md §9 rule 4: never re-normalize "
            "the same JD — LLM cost scales with users otherwise."
        ),
    )
    title: str = Field(..., min_length=1)
    company: str | None = None
    location: str | None = None
    country: str | None = Field(
        default=None,
        description="ISO 3166-1 alpha-2 where known (KH, SG, JP, AU), or 'REMOTE'.",
    )
    industry: str
    seniority: Seniority
    years_exp_required: float | None = Field(default=None, ge=0, le=50)
    education_required: str | None = None
    sponsors_visa: SponsorsVisa = Field(
        default="unstated",
        description="F6 visa signal. 'unstated' is the honest default — silence is not a 'no'.",
    )
    # CP1: requested by Person B — Phase 4.5 shows the visa verdict *with the JD
    # sentence that triggered it*. A bare yes/no/unstated is not defensible on screen.
    sponsors_visa_source_line: str | None = Field(
        default=None,
        description="Verbatim JD sentence the sponsors_visa value was read from. None when unstated.",
    )
    salary_range: str | None = None
    requirements: list[Requirement] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _unique_requirement_ids(cls, v: list[Requirement]) -> list[Requirement]:
        ids = [r.id for r in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate requirement ids: {dupes}")
        return v

    @property
    def required_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.priority == "required"]


# ── Resume ────────────────────────────────────────────────────────────────────


class Education(_Base):
    degree: str
    institution: str
    year: int | None = Field(default=None, ge=1950, le=2100)
    gpa: str | None = Field(
        default=None,
        description="Free text on purpose — '3.5+', '2:1', 'First Class' are all real.",
    )


class Evidence(_Base):
    """One thing the candidate has actually done.

    F4 is the whole project: a fresh graduate has no employment bullet points, so
    coursework, projects and part-time work must be first-class evidence records
    rather than second-class text.
    """

    id: str = Field(
        ...,
        pattern=r"^e\d+$",
        description="Stable within one resume: e1, e2, … Cited by MatchResult.evidence_ids and facts_used.",
        examples=["e1"],
    )
    source_line: str = Field(
        ...,
        min_length=1,
        description=(
            "Verbatim line from the resume. The results screen highlights this exact "
            "string, and the F5 rewrite validator checks generated claims against it."
        ),
    )
    evidence_type: EvidenceType
    skills: list[str] = Field(default_factory=list)
    duration_months: int | None = Field(default=None, ge=0, le=600)
    team_size: int | None = Field(default=None, ge=1)
    outcome: str | None = None

    @property
    def is_employment(self) -> bool:
        """True only for paid professional work. Internships and part-time count.

        ``NON_EMPLOYMENT_EVIDENCE`` covers the four academic and unpaid types;
        ``certification`` is neither, being a credential rather than a span of work.
        """
        return self.evidence_type in {"employment", "internship", "part_time"}


class Resume(_Base):
    candidate_summary: str = Field(default="", description="One paragraph. May be empty.")
    total_years_work: float = Field(
        default=0.0,
        ge=0,
        le=60,
        description="Paid employment only. A fresh graduate is 0.0 and that is fine.",
    )
    education: list[Education] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _unique_evidence_ids(cls, v: list[Evidence]) -> list[Evidence]:
        ids = [e.id for e in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate evidence ids: {dupes}")
        return v

    def evidence_by_id(self, evidence_id: str) -> Evidence | None:
        return next((e for e in self.evidence if e.id == evidence_id), None)


# ── Match ─────────────────────────────────────────────────────────────────────


class MatchResult(_Base):
    """One verdict, for one requirement.

    Not a score — a verdict, with its receipt. PROJECT_SPEC.md §9 rule 3 is
    enforced by ``_traceable`` below: no verdict may exist without either cited
    evidence or a stated reason for its absence.
    """

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    verdict: Verdict
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence.id values supporting this verdict. Must be empty when verdict is 'missing'.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="One sentence, English. Displayed under the expanded requirement row.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    missing_reason: str | None = Field(
        default=None,
        description="Required when verdict is 'missing'. Rendered as the explicit 'why not' line.",
    )

    @model_validator(mode="after")
    def _traceable(self) -> MatchResult:
        """PROJECT_SPEC.md §9 rule 3 — every verdict is traceable."""
        if self.verdict == "missing":
            if self.evidence_ids:
                raise ValueError(
                    f"{self.requirement_id}: verdict 'missing' cannot cite evidence "
                    f"{self.evidence_ids} — use 'partial' if the evidence is adjacent."
                )
            if not (self.missing_reason or "").strip():
                raise ValueError(
                    f"{self.requirement_id}: verdict 'missing' requires an explicit "
                    "missing_reason (rule 3: every verdict is traceable)."
                )
        else:
            if not self.evidence_ids:
                raise ValueError(
                    f"{self.requirement_id}: verdict '{self.verdict}' must cite at least "
                    "one evidence_id (rule 3: every verdict is traceable)."
                )
            if self.missing_reason is not None:
                raise ValueError(
                    f"{self.requirement_id}: missing_reason is only valid on a 'missing' verdict."
                )
        return self


class HiddenStrength(_Base):
    """F5 — a requirement the resume already satisfies but phrases badly.

    Produced by ``engine.rewrite`` (Person B, Phase 3). ``suggested_phrasing`` is
    generated from the evidence records *only* — never from the raw resume and
    never from the JD — and every claim in it must trace to ``facts_used``.
    """

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    evidence_id: str = Field(..., pattern=r"^e\d+$")
    current_phrasing: str = Field(..., min_length=1, description="Verbatim from the resume.")
    suggested_phrasing: str = Field(..., min_length=1, description="Rewritten. No new facts.")
    facts_used: list[str] = Field(
        ...,
        min_length=1,
        description="Evidence.id values every claim in suggested_phrasing traces to.",
    )
    # CP1: requested by Person B — Phase 4.3 renders a word-level before/after diff.
    # Computing it in the engine keeps the UI dumb and the diff reproducible in the report.
    changed_words: list[str] = Field(
        default_factory=list,
        description="Words in suggested_phrasing absent from current_phrasing. Highlighted in the UI.",
    )

    @model_validator(mode="after")
    def _cites_its_own_evidence(self) -> HiddenStrength:
        if self.evidence_id not in self.facts_used:
            raise ValueError(
                f"{self.requirement_id}: evidence_id {self.evidence_id!r} must appear in "
                f"facts_used {self.facts_used} (rule 1: every generated claim cites its source)."
            )
        return self


class PriorityAction(_Base):
    """One entry in the 'what to fix first' rail.

    PROJECT_SPEC.md §8 types ``priority_actions`` as a list of plain strings.
    PERSON_B_PLAN_v2.md Phase 2.1 and 4.6 need each action to link to the
    requirement row it addresses and to show its coverage gain. Both are satisfied:
    a bare string still parses (see ``_accept_bare_string``), so Person A's engine
    may keep emitting strings and the UI degrades to a plain ordered list.
    """

    text: str = Field(..., min_length=1)
    requirement_id: str | None = Field(
        default=None,
        pattern=r"^r\d+$",
        description="Anchor for the 'jump to requirement' link. None when the action is general.",
    )
    coverage_gain: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Estimated percentage-point gain in coverage_required_only. Rendered as '+8%'.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_string(cls, data: Any) -> Any:
        """Let ``"Learn SQL"`` parse as ``PriorityAction(text="Learn SQL")``."""
        if isinstance(data, str):
            return {"text": data}
        return data


class BaselineResult(_Base):
    """One TF-IDF keyword-overlap verdict, for the comparison column."""

    requirement_id: str = Field(..., pattern=r"^r\d+$")
    verdict: Verdict
    score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity of the TF-IDF vectors.")
    matched_terms: list[str] = Field(default_factory=list)


class BaselineMatch(_Base):
    """The keyword matcher, run on the same pair.

    This exists to be beaten. It is the comparison column in the evaluation chapter
    and the 'Compare with keyword baseline' toggle on the results screen — the one
    control that makes the argument visible instead of narrated.
    """

    method: Literal["tfidf"] = "tfidf"
    coverage_score: float = Field(..., ge=0.0, le=100.0)
    results: list[BaselineResult] = Field(default_factory=list)


class Match(_Base):
    """The full analysis of one resume against one job.

    ``job`` and ``resume`` are embedded so a stored match is self-contained: the
    results screen, the golden fixtures and the Phase 6 evaluation export all need
    the requirement text and the evidence lines beside the verdicts, and re-joining
    them from three tables at render time buys nothing.
    """

    coverage_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="All requirements, weighted required-over-preferred. Weighting lives in engine/match/.",
    )
    coverage_required_only: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Required requirements only. The honest headline number.",
    )
    realism_verdict: RealismVerdict
    realism_explanation: str | None = Field(
        default=None,
        description="One plain-language line under the realism badge. English; km translation is Phase 5.7.",
    )
    results: list[MatchResult] = Field(default_factory=list)
    hidden_strengths: list[HiddenStrength] = Field(default_factory=list)
    priority_actions: list[PriorityAction] = Field(default_factory=list)

    # CP1: requested by Person B — the evaluation chapter must state which engine
    # version produced each row, and must be able to freeze at v1.0-freeze.
    engine_version: str = Field(
        default=SCHEMA_VERSION,
        description="Engine version that produced this match. Recorded in eval/system_outputs.json.",
    )
    generated_at: datetime = Field(
        default_factory=utcnow,
        description="UTC, timezone-aware.",
    )

    job: Job | None = Field(default=None, description="The job this match was computed against.")
    resume: Resume | None = Field(default=None, description="The resume this match was computed for.")

    # ── cross-field integrity ────────────────────────────────────────────────

    @model_validator(mode="after")
    def _one_result_per_requirement(self) -> Match:
        ids = [r.requirement_id for r in self.results]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"more than one verdict for requirement(s): {dupes}")
        return self

    @model_validator(mode="after")
    def _references_resolve(self) -> Match:
        """Every id cited anywhere must exist in the embedded job / resume.

        Skipped when the match is stored without its job or resume — a bare Match
        is still legal, it just cannot be integrity-checked.
        """
        if self.job is not None:
            known_reqs = {r.id for r in self.job.requirements}
            cited = {r.requirement_id for r in self.results}
            cited |= {h.requirement_id for h in self.hidden_strengths}
            cited |= {a.requirement_id for a in self.priority_actions if a.requirement_id}
            unknown = sorted(cited - known_reqs)
            if unknown:
                raise ValueError(f"results reference requirement ids absent from the job: {unknown}")

            uncovered = sorted(known_reqs - {r.requirement_id for r in self.results})
            if uncovered:
                raise ValueError(
                    f"no verdict for requirement(s) {uncovered} — every requirement gets a "
                    "verdict, even if that verdict is 'missing' (rule 3)."
                )

        if self.resume is not None:
            known_ev = {e.id for e in self.resume.evidence}
            cited_ev: set[str] = set()
            for r in self.results:
                cited_ev |= set(r.evidence_ids)
            for h in self.hidden_strengths:
                cited_ev.add(h.evidence_id)
                cited_ev |= set(h.facts_used)
            unknown_ev = sorted(cited_ev - known_ev)
            if unknown_ev:
                raise ValueError(f"cited evidence ids absent from the resume: {unknown_ev}")

        return self

    @model_validator(mode="after")
    def _enforce_no_scope_inflation(self) -> Match:
        """PROJECT_SPEC.md §9 rule 2 / F4, as code rather than as a prompt.

        A four-month class project is not two years of professional experience. So:
        an ``experience`` requirement may not be ``proven`` by evidence that is only
        coursework, a project, a competition or volunteering. ``partial`` is exactly
        what those records are for, and stays allowed.

        Requires the embedded job and resume; a bare Match cannot be checked.
        """
        if self.job is None or self.resume is None:
            return self

        req_by_id = {r.id: r for r in self.job.requirements}
        ev_by_id = {e.id: e for e in self.resume.evidence}

        for result in self.results:
            if result.verdict != "proven":
                continue
            requirement = req_by_id.get(result.requirement_id)
            if requirement is None or requirement.category != "experience":
                continue

            cited = [ev_by_id[i] for i in result.evidence_ids if i in ev_by_id]
            if cited and not any(e.is_employment for e in cited):
                offenders = sorted(
                    {e.evidence_type for e in cited if e.evidence_type in NON_EMPLOYMENT_EVIDENCE}
                )
                raise ValueError(
                    f"{result.requirement_id}: experience requirement marked 'proven' using only "
                    f"non-employment evidence {offenders}. PROJECT_SPEC.md §9 rule 2 forbids "
                    "upgrading a project into professional experience — use 'partial'."
                )
        return self

    # ── convenience for the API and the fixtures ─────────────────────────────

    def results_by_verdict(self, verdict: Verdict) -> list[MatchResult]:
        return [r for r in self.results if r.verdict == verdict]

    @property
    def counts(self) -> dict[str, int]:
        """``{'proven': 3, 'partial': 4, 'missing': 2}`` — the headline tally."""
        return {v: len(self.results_by_verdict(v)) for v in ("proven", "partial", "missing")}


class SchemaBundle(_Base):
    """Every top-level model in one object, so one JSON Schema export covers all.

    Not used at runtime. ``scripts/export_schema.py`` calls
    ``SchemaBundle.model_json_schema()`` and hands the ``$defs`` to
    json-schema-to-typescript, which is how ``web/lib/types.ts`` stays honest.
    """

    job: Job
    resume: Resume
    match: Match
    baseline: BaselineMatch
