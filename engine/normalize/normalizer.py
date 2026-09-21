"""Gemini LLM normalizer for Job Descriptions and Resumes.

OWNER: Person A (Dy David)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

from engine.gemini_client import (
    generate_structured_json,
    get_extract_model,
    get_gemini_api_key,
)
from engine.normalize.parser import parse_resume_bytes
from engine.normalize.schema import (
    Education,
    Evidence,
    EvidenceType,
    Job,
    Requirement,
    RequirementCategory,
    RequirementPriority,
    Resume,
    Seniority,
    SponsorsVisa,
)

logger = logging.getLogger(__name__)


# ── Gemini Response Pydantic DTO Schemas ─────────────────────────────────────


class _RequirementLLM(BaseModel):
    text: str = Field(description="Verbatim requirement quoted from the job post.")
    category: str = Field(description="hard_skill | soft_skill | education | certification | experience | language")
    priority: str = Field(description="required | preferred")
    normalized_skill: str | None = Field(default=None, description="Canonical skill name if applicable (e.g., 'React', 'Python')")


class _JobLLM(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    country: str | None = Field(default=None, description="ISO alpha-2 code e.g. KH, SG, US, or REMOTE")
    industry: str = "Technology"
    seniority: str = Field(default="entry", description="intern | entry | junior | mid | senior")
    years_exp_required: float | None = None
    education_required: str | None = None
    sponsors_visa: str = Field(default="unstated", description="yes | no | unstated")
    sponsors_visa_source_line: str | None = None
    salary_range: str | None = None
    requirements: list[_RequirementLLM] = Field(default_factory=list)


class _EducationLLM(BaseModel):
    degree: str
    institution: str
    year: int | None = None
    gpa: str | None = None


class _EvidenceLLM(BaseModel):
    source_line: str = Field(description="Verbatim or close sentence from the resume describing what candidate did")
    evidence_type: str = Field(
        description="employment | internship | part_time | coursework | project | volunteer | certification | competition"
    )
    skills: list[str] = Field(default_factory=list)
    duration_months: int | None = None
    team_size: int | None = None
    outcome: str | None = None


class _ResumeLLM(BaseModel):
    candidate_summary: str = ""
    total_years_work: float = 0.0
    education: list[_EducationLLM] = Field(default_factory=list)
    evidence: list[_EvidenceLLM] = Field(default_factory=list)


# ── Helper to load golden fixtures ───────────────────────────────────────────


def _load_golden_fixture() -> dict:
    """Load golden fixture JSON file."""
    fixtures_dir = Path(__file__).parents[2] / "data" / "fixtures"
    fixture_path = fixtures_dir / "fresh_grad_strong_fit.json"
    if fixture_path.exists():
        with open(fixture_path, encoding="utf-8") as f:
            return json.load(f)
    raise RuntimeError(f"Golden fixture file not found at {fixture_path}")


# ── In-Memory Normalization Cache ─────────────────────────────────────────────
_JD_CACHE: dict[str, Job] = {}
_RESUME_CACHE: dict[str, Resume] = {}


def clear_normalizer_cache() -> None:
    """Clear in-memory cache for normalized JDs and Resumes."""
    _JD_CACHE.clear()
    _RESUME_CACHE.clear()


# ── Normalizer Callables ──────────────────────────────────────────────────────


def normalize_jd_text(text: str) -> Job:
    """Normalize raw job description text into a schema Job."""
    if not text or not text.strip():
        raise ValueError("Job description text is empty")

    clean_text = text.strip()
    content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:16]

    # Check cache first to save LLM tokens
    if content_hash in _JD_CACHE:
        return _JD_CACHE[content_hash]

    # Check mock mode or missing API key
    api_key = get_gemini_api_key()
    if os.getenv("ENGINE_MODE") == "mock" or not api_key:
        fixture_data = _load_golden_fixture()
        job_data = fixture_data["job"]
        job_data["content_hash"] = content_hash
        res = Job.model_validate(job_data)
        _JD_CACHE[content_hash] = res
        return res

    prompt = f"""
    Analyze and extract all structured data from the following job description.

    Instructions:
    1. title: Extract the specific role/job title (e.g. 'Junior Web Developer', 'Sales Representative', 'Finance Intern'). Infer from duties if not explicitly labeled. Never return 'Not specified'.
    2. company: Company or employer name (e.g. 'TotalEnergies Marketing (Cambodia) Co., Ltd.').
    3. location & country: Location e.g. 'Phnom Penh, Cambodia' and ISO country code 'KH', 'SG', 'US', etc.
    4. requirements: Extract EVERY requirement, required skill, preferred tool, responsibility, language, education level, and experience mentioned. Quote verbatim or summarize accurately. Extract at least 3-10 distinct requirements.
    5. priority: Tag as 'required' (must-have/mandatory) or 'preferred' (nice-to-have/plus).
    6. category: Classify each as hard_skill, soft_skill, education, certification, experience, or language.

    Job Description:
    {clean_text}
    """

    try:
        dto = generate_structured_json(
            prompt=prompt,
            response_schema=_JobLLM,
            model_name=get_extract_model(),
            temperature=0.0,
            system_instruction="You are an expert recruitment parser. Extract job description requirements accurately and thoroughly into structured JSON.",
            thinking_budget=0,
        )


        reqs: list[Requirement] = []
        for idx, r in enumerate(dto.requirements):
            category: RequirementCategory = r.category if r.category in (
                "hard_skill", "soft_skill", "education", "certification", "experience", "language"
            ) else "hard_skill"
            
            priority: RequirementPriority = r.priority if r.priority in ("required", "preferred") else "required"

            reqs.append(
                Requirement(
                    id=f"r{idx + 1}",
                    text=r.text,
                    category=category,
                    priority=priority,
                    normalized_skill=r.normalized_skill,
                    display_order=idx,
                )
            )

        seniority_val: Seniority = dto.seniority if dto.seniority in (
            "intern", "entry", "junior", "mid", "senior"
        ) else "entry"

        sponsors_visa_val: SponsorsVisa = dto.sponsors_visa if dto.sponsors_visa in (
            "yes", "no", "unstated"
        ) else "unstated"

        result = Job(
            source_url=None,
            source_type="pasted",
            content_hash=content_hash,
            title=dto.title or "Job Position",
            company=dto.company,
            location=dto.location,
            country=dto.country,
            industry=dto.industry or "Technology",
            seniority=seniority_val,
            years_exp_required=dto.years_exp_required,
            education_required=dto.education_required,
            sponsors_visa=sponsors_visa_val,
            sponsors_visa_source_line=dto.sponsors_visa_source_line,
            salary_range=dto.salary_range,
            requirements=reqs,
        )
        _JD_CACHE[content_hash] = result
        return result
    except Exception as err:
        logger.warning("Gemini JD normalizer failed: %s. Using fallback fixture.", err)
        fixture_data = _load_golden_fixture()
        job_data = fixture_data["job"]
        job_data["content_hash"] = content_hash
        res = Job.model_validate(job_data)
        _JD_CACHE[content_hash] = res
        return res


def normalize_resume_file(file_bytes: bytes, filename: str) -> Resume:
    """Normalize raw uploaded resume file into a schema Resume."""
    raw_text = parse_resume_bytes(file_bytes, filename)
    if not raw_text or not raw_text.strip():
        raise ValueError("Resume file yielded no extractable text")

    clean_text = raw_text.strip()
    resume_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:16]

    # Check cache first to save LLM tokens
    if resume_hash in _RESUME_CACHE:
        return _RESUME_CACHE[resume_hash]

    api_key = get_gemini_api_key()
    if os.getenv("ENGINE_MODE") == "mock" or not api_key:
        fixture_data = _load_golden_fixture()
        res = Resume.model_validate(fixture_data["resume"])
        _RESUME_CACHE[resume_hash] = res
        return res

    prompt = f"""
    Extract comprehensive candidate info and ALL individual evidence records from this resume text:

    EVIDENCE EXTRACTION RULES:
    - Handle varied resume headings flexibly (e.g., Education, Academic Background, Qualifications, Degrees, Courses, Relevant Coursework, Key Modules, Training, Projects, Practical Work, Extracurriculars, Core Competencies).
    1. Education & Degrees: Extract all universities, colleges, degrees, diplomas, and expected graduation dates.
    2. Work & Volunteer: Extract each role and bullet point as 'employment', 'internship', 'part_time', or 'volunteer'.
    3. Projects & Hackathons: Extract every project, startup, or practical system built as 'project'.
    4. Competitions & Awards: Extract every competition, medal, contest, or award as 'competition'.
    5. Certifications: Extract every professional certificate, qualification, or exam as 'certification'.
    6. Coursework & Modules: Extract relevant subjects/courses/modules studied as 'coursework'.
    7. Skills & Languages: Extract all listed technical skills, software tools, and LANGUAGE PROFICIENCIES (e.g., "Bilingual in English and Khmer", "SQL Database Management") as evidence lines with their specific 'skills' tags populated.

    Keep source_line verbatim or as close as possible to the resume text.

    Resume text:
    {raw_text}
    """

    try:
        dto = generate_structured_json(
            prompt=prompt,
            response_schema=_ResumeLLM,
            model_name=get_extract_model(),
            temperature=0.0,
            system_instruction="You are an expert resume parsing engine. Parse candidate evidence, skills, languages, and achievements comprehensively into structured JSON.",
            thinking_budget=0,
        )


        edu_list: list[Education] = [
            Education(
                degree=e.degree,
                institution=e.institution,
                year=e.year,
                gpa=e.gpa,
            )
            for e in dto.education
        ]

        ev_list: list[Evidence] = []
        
        # 1. Include Education degrees as primary evidence records
        for edu in edu_list:
            deg_line = f"{edu.degree} — {edu.institution}" + (f" ({edu.year})" if edu.year else "")
            ev_list.append(
                Evidence(
                    id=f"e{len(ev_list) + 1}",
                    source_line=deg_line,
                    evidence_type="coursework",
                    skills=[edu.degree],
                )
            )

        # 2. Include all other parsed evidence items
        for ev in dto.evidence:
            # Skip if exact duplicate of education degree
            if any(ev.source_line.lower() in existing.source_line.lower() for existing in ev_list):
                continue

            ev_type: EvidenceType = ev.evidence_type if ev.evidence_type in (
                "employment", "internship", "part_time", "coursework", "project", "volunteer", "certification", "competition"
            ) else "project"

            ev_list.append(
                Evidence(
                    id=f"e{len(ev_list) + 1}",
                    source_line=ev.source_line,
                    evidence_type=ev_type,
                    skills=ev.skills,
                    duration_months=ev.duration_months,
                    team_size=ev.team_size,
                    outcome=ev.outcome,
                )
            )

        result = Resume(
            candidate_summary=dto.candidate_summary or "",
            total_years_work=max(0.0, float(dto.total_years_work or 0.0)),
            education=edu_list,
            evidence=ev_list,
        )
        _RESUME_CACHE[resume_hash] = result
        return result
    except Exception as err:
        logger.warning("Gemini Resume normalizer failed: %s. Using fallback fixture.", err)
        fixture_data = _load_golden_fixture()
        res = Resume.model_validate(fixture_data["resume"])
        _RESUME_CACHE[resume_hash] = res
        return res
