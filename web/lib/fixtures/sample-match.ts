import type { Match } from "@/lib/types";

/**
 * Phase 1 "skeleton" sample data (PERSON_B_PLAN_v2.md §5 Phase 1 task 5).
 *
 * No mock API exists yet — that is a separate Phase 1 task (fixtures +
 * FastAPI mock mode). This object renders the Results screen end to end
 * against Person A's locked schema so the UI can be built and demoed before
 * either of those exist. Numbers and wording are illustrative, modeled on a
 * real AUPP-style resume against a real Junior Software Developer post, in
 * Proofit's voice (BRAND.md §6): no invented experience, no ATS framing.
 */
export const sampleMatch: Match = {
  coverage_score: 68,
  coverage_required_only: 61,
  engine_version: "fixture-0.1",
  generated_at: "2026-09-10T09:00:00Z",
  realism_verdict: "stretch",
  realism_explanation:
    "You cover 4 of 6 required skills. The two-year experience requirement is the main risk; your capstone project counts as partial evidence, not full.",
  job: {
    title: "Junior Software Developer",
    company: "DGC Cambodia",
    content_hash: "fixture-job-001",
    country: "KH",
    location: "Phnom Penh",
    industry: "Software",
    seniority: "junior",
    source_type: "pasted",
    years_exp_required: 2,
    sponsors_visa: "unstated",
    sponsors_visa_source_line: null,
    requirements: [
      {
        id: "r1",
        text: "Experience with Docker and CI/CD pipelines",
        category: "hard_skill",
        priority: "required",
        normalized_skill: "Docker",
        display_order: 0,
      },
      {
        id: "r2",
        text: "Knowledge of PostgreSQL query optimization",
        category: "hard_skill",
        priority: "required",
        normalized_skill: "PostgreSQL",
        display_order: 1,
      },
      {
        id: "r3",
        text: "Familiarity with Kubernetes",
        category: "hard_skill",
        priority: "preferred",
        normalized_skill: "Kubernetes",
        display_order: 2,
      },
      {
        id: "r4",
        text: "2+ years of experience building REST APIs",
        category: "experience",
        priority: "required",
        normalized_skill: "REST APIs",
        display_order: 3,
      },
      {
        id: "r5",
        text: "Experience supporting production systems",
        category: "experience",
        priority: "required",
        display_order: 4,
      },
      {
        id: "r6",
        text: "Bachelor's degree in Computer Science or related field",
        category: "education",
        priority: "preferred",
        display_order: 5,
      },
      {
        id: "r7",
        text: "Strong written English",
        category: "soft_skill",
        priority: "preferred",
        display_order: 6,
      },
      {
        id: "r8",
        text: "Git in a team setting",
        category: "hard_skill",
        priority: "required",
        normalized_skill: "Git",
        display_order: 7,
      },
      {
        id: "r9",
        text: "Python",
        category: "hard_skill",
        priority: "required",
        normalized_skill: "Python",
        display_order: 8,
      },
      {
        id: "r10",
        text: "Customer-facing communication",
        category: "soft_skill",
        priority: "preferred",
        display_order: 9,
      },
      {
        id: "r11",
        text: "Khmer and English fluency",
        category: "language",
        priority: "preferred",
        display_order: 10,
      },
      {
        id: "r12",
        text: "Basic SQL",
        category: "hard_skill",
        priority: "preferred",
        normalized_skill: "SQL",
        display_order: 11,
      },
    ],
  },
  resume: {
    candidate_summary:
      "Final-year Computer Science student with project and part-time support experience.",
    total_years_work: 0,
    education: [
      {
        degree: "B.Sc. ICT (Software Development & Project Management)",
        institution: "American University of Phnom Penh",
        year: 2027,
        gpa: "3.5",
      },
    ],
    evidence: [
      {
        id: "e14",
        evidence_type: "part_time",
        source_line:
          "Part-time Technical Support, DGC Cambodia: resolved 30+ tickets a week for internal systems, escalating server incidents to the backend team.",
        duration_months: 8,
      },
      {
        id: "e15",
        evidence_type: "part_time",
        source_line:
          "First point of contact for 40 staff on hardware and account issues, in Khmer and English.",
        duration_months: 8,
      },
      {
        id: "e21",
        evidence_type: "project",
        source_line:
          "Built the backend for an inventory-tracking web app (FastAPI, PostgreSQL) as a 4-month team capstone project with 3 other students.",
        duration_months: 4,
        team_size: 4,
        skills: ["Python", "FastAPI", "PostgreSQL"],
      },
      {
        id: "e22",
        evidence_type: "project",
        source_line:
          "Designed 14 REST endpoints and wrote the OpenAPI documentation.",
        duration_months: 4,
        team_size: 4,
      },
      {
        id: "e23",
        evidence_type: "project",
        source_line:
          "Managed the team's GitHub repository with feature branches, pull-request reviews and a protected main branch.",
        duration_months: 4,
        team_size: 4,
        skills: ["Git"],
      },
      {
        id: "e31",
        evidence_type: "coursework",
        source_line:
          "Database Systems (ICT 210): designed a normalized schema and wrote reporting queries with joins and aggregates.",
        skills: ["SQL"],
      },
      {
        id: "e38",
        evidence_type: "coursework",
        source_line: "Khmer (native), English (professional working).",
      },
    ],
  },
  results: [
    {
      requirement_id: "r1",
      verdict: "missing",
      confidence: 0.88,
      evidence_ids: [],
      missing_reason:
        "No evidence record mentions Docker, containers, CI, GitHub Actions, Jenkins or deployment automation.",
      reasoning:
        "Because the requirement is required, this is the first thing to close. Containerizing your capstone repository with a GitHub Actions workflow would move this to partial with real evidence.",
    },
    {
      requirement_id: "r2",
      verdict: "missing",
      confidence: 0.74,
      evidence_ids: [],
      missing_reason:
        "The resume lists PostgreSQL as a skill (e21), but no evidence record shows indexing, query plans or performance work. A bare skill mention does not count as evidence.",
      reasoning:
        "The skill is named but not demonstrated at the level this requirement asks for.",
    },
    {
      requirement_id: "r3",
      verdict: "missing",
      confidence: 0.95,
      evidence_ids: [],
      missing_reason: "No evidence. Preferred, so it counts half.",
      reasoning: "Not a priority action — preferred and unevidenced.",
    },
    {
      requirement_id: "r4",
      verdict: "partial",
      confidence: 0.81,
      evidence_ids: ["e21", "e22"],
      reasoning:
        "A 4-month team project is partial evidence for a 2-year experience requirement. The skill is proven; the duration is not.",
    },
    {
      requirement_id: "r5",
      verdict: "partial",
      confidence: 0.7,
      evidence_ids: ["e14"],
      reasoning:
        "Support of production systems is real, but from the ticket side rather than the engineering side.",
    },
    {
      requirement_id: "r6",
      verdict: "partial",
      confidence: 0.92,
      evidence_ids: [],
      reasoning:
        "Related field and in progress. Partial because the degree is not yet completed; becomes proven on graduation.",
    },
    {
      requirement_id: "r7",
      verdict: "partial",
      confidence: 0.6,
      evidence_ids: ["e22"],
      reasoning:
        "No test score listed; the OpenAPI documentation line is the only direct evidence.",
    },
    {
      requirement_id: "r8",
      verdict: "proven",
      confidence: 0.96,
      evidence_ids: ["e23"],
      reasoning: "Explicit team Git workflow with reviewed pull requests.",
    },
    {
      requirement_id: "r9",
      verdict: "proven",
      confidence: 0.98,
      evidence_ids: ["e21"],
      reasoning: "Python named directly as the backend implementation language.",
    },
    {
      requirement_id: "r10",
      verdict: "proven",
      confidence: 0.9,
      evidence_ids: ["e15"],
      reasoning: "Direct customer-facing support role, bilingual.",
    },
    {
      requirement_id: "r11",
      verdict: "proven",
      confidence: 0.99,
      evidence_ids: ["e38"],
      reasoning: "Stated directly on the resume.",
    },
    {
      requirement_id: "r12",
      verdict: "proven",
      confidence: 0.93,
      evidence_ids: ["e31"],
      reasoning: "Coursework demonstrates joins and aggregate queries.",
    },
  ],
  priority_actions: [
    {
      requirement_id: "r1",
      text: "Containerize your capstone with Docker and add a GitHub Actions workflow.",
      coverage_gain: 9,
    },
    {
      requirement_id: "r4",
      text: "Rephrase the REST API project so the duration and team size are explicit.",
      coverage_gain: 4,
    },
    {
      requirement_id: "r2",
      text: "Add one line about PostgreSQL performance work from ICT 210, if you did any indexing.",
    },
  ],
};
