/* eslint-disable */
/**
 * =============================================================================
 *  GENERATED - DO NOT EDIT BY HAND.  Run scripts/gen-types.sh
 * =============================================================================
 *
 *  Source of truth:  engine/normalize/schema.py
 *                    (Person A's locked Pydantic schema - PERSON_B_PLAN_v2.md
 *                    §2 "the contract between you": never hand-write a type that
 *                    already exists in the schema.)
 *
 *  Pipeline:         engine/normalize/schema.py
 *                      -> scripts/export_schema.py
 *                      -> web/lib/schema.json
 *                      -> json-schema-to-typescript@16
 *                      -> web/lib/types.ts   (this file)
 *
 *  To change a type, edit engine/normalize/schema.py and run:
 *
 *      bash scripts/gen-types.sh
 *
 *  Every edit made directly to this file is destroyed on the next run, and CI
 *  fails the build when this file no longer matches the schema. If the live
 *  engine disagrees with the UI, fix the schema and the fixtures - not this file.
 *
 *  Schema version:   0.1.0-provisional
 */

/**
 * Every top-level model in one object, so one JSON Schema export covers all.
 *
 * Not used at runtime. ``scripts/export_schema.py`` calls
 * ``SchemaBundle.model_json_schema()`` and hands the ``$defs`` to
 * json-schema-to-typescript, which is how ``web/lib/types.ts`` stays honest.
 */
export interface SchemaBundle {
  baseline: BaselineMatch;
  job: Job;
  match: Match;
  resume: Resume;
}
/**
 * The keyword matcher, run on the same pair.
 *
 * This exists to be beaten. It is the comparison column in the evaluation chapter
 * and the 'Compare with keyword baseline' toggle on the results screen — the one
 * control that makes the argument visible instead of narrated.
 */
export interface BaselineMatch {
  coverage_score: number;
  method?: "tfidf";
  results?: BaselineResult[];
}
/**
 * One TF-IDF keyword-overlap verdict, for the comparison column.
 */
export interface BaselineResult {
  matched_terms?: string[];
  requirement_id: string;
  /**
   * Cosine similarity of the TF-IDF vectors.
   */
  score: number;
  verdict: "proven" | "partial" | "missing";
}
/**
 * A normalized job description, from any source: paste, URL or scraper.
 */
export interface Job {
  company?: string | null;
  /**
   * Hash of the raw JD text. PROJECT_SPEC.md §9 rule 4: never re-normalize the same JD — LLM cost scales with users otherwise.
   */
  content_hash: string;
  /**
   * ISO 3166-1 alpha-2 where known (KH, SG, JP, AU), or 'REMOTE'.
   */
  country?: string | null;
  education_required?: string | null;
  industry: string;
  location?: string | null;
  requirements?: Requirement[];
  salary_range?: string | null;
  seniority: "intern" | "entry" | "junior" | "mid" | "senior";
  source_type: "scraped" | "pasted";
  source_url?: string | null;
  /**
   * F6 visa signal. 'unstated' is the honest default — silence is not a 'no'.
   */
  sponsors_visa?: "yes" | "no" | "unstated";
  /**
   * Verbatim JD sentence the sponsors_visa value was read from. None when unstated.
   */
  sponsors_visa_source_line?: string | null;
  title: string;
  years_exp_required?: number | null;
}
/**
 * One requirement, extracted verbatim from the job post.
 *
 * One record per requirement — never a bundled sentence. ``text`` is quoted back
 * to the user on the results screen, so it must be the JD's own words.
 */
export interface Requirement {
  category: "hard_skill" | "soft_skill" | "education" | "certification" | "experience" | "language" | "other";
  /**
   * Zero-based position in the original JD. None if the normalizer did not record it.
   */
  display_order?: number | null;
  /**
   * Stable within one job: r1, r2, … Referenced by MatchResult.requirement_id.
   */
  id: string;
  /**
   * Canonical skill name, e.g. 'React'. None when the requirement names no single skill.
   */
  normalized_skill?: string | null;
  /**
   * From JD wording: 'must have' → required, 'nice to have' → preferred.
   */
  priority: "required" | "preferred";
  /**
   * Verbatim requirement from the JD. Shown in English regardless of UI locale.
   */
  text: string;
}
/**
 * The full analysis of one resume against one job.
 *
 * ``job`` and ``resume`` are embedded so a stored match is self-contained: the
 * results screen, the golden fixtures and the Phase 6 evaluation export all need
 * the requirement text and the evidence lines beside the verdicts, and re-joining
 * them from three tables at render time buys nothing.
 */
export interface Match {
  /**
   * Required requirements only. The honest headline number.
   */
  coverage_required_only: number;
  /**
   * All requirements, weighted required-over-preferred. Weighting lives in engine/match/.
   */
  coverage_score: number;
  /**
   * Engine version that produced this match. Recorded in eval/system_outputs.json.
   */
  engine_version?: string;
  /**
   * UTC, timezone-aware.
   */
  generated_at?: string;
  hidden_strengths?: HiddenStrength[];
  /**
   * The job this match was computed against.
   */
  job?: Job | null;
  priority_actions?: PriorityAction[];
  /**
   * One plain-language line under the realism badge. English; km translation is Phase 5.7.
   */
  realism_explanation?: string | null;
  realism_verdict: "strong_fit" | "stretch" | "unrealistic";
  results?: MatchResult[];
  /**
   * The resume this match was computed for.
   */
  resume?: Resume | null;
}
/**
 * F5 — a requirement the resume already satisfies but phrases badly.
 *
 * Produced by ``engine.rewrite`` (Person B, Phase 3). ``suggested_phrasing`` is
 * generated from the evidence records *only* — never from the raw resume and
 * never from the JD — and every claim in it must trace to ``facts_used``.
 */
export interface HiddenStrength {
  /**
   * Words in suggested_phrasing absent from current_phrasing. Highlighted in the UI.
   */
  changed_words?: string[];
  /**
   * Verbatim from the resume.
   */
  current_phrasing: string;
  evidence_id: string;
  /**
   * Evidence.id values every claim in suggested_phrasing traces to.
   *
   * @minItems 1
   */
  facts_used: [string, ...string[]];
  requirement_id: string;
  /**
   * Rewritten. No new facts.
   */
  suggested_phrasing: string;
}
/**
 * One entry in the 'what to fix first' rail.
 *
 * PROJECT_SPEC.md §8 types ``priority_actions`` as a list of plain strings.
 * PERSON_B_PLAN_v2.md Phase 2.1 and 4.6 need each action to link to the
 * requirement row it addresses and to show its coverage gain. Both are satisfied:
 * a bare string still parses (see ``_accept_bare_string``), so Person A's engine
 * may keep emitting strings and the UI degrades to a plain ordered list.
 */
export interface PriorityAction {
  /**
   * Estimated percentage-point gain in coverage_required_only. Rendered as '+8%'.
   */
  coverage_gain?: number | null;
  /**
   * Anchor for the 'jump to requirement' link. None when the action is general.
   */
  requirement_id?: string | null;
  text: string;
}
/**
 * One verdict, for one requirement.
 *
 * Not a score — a verdict, with its receipt. PROJECT_SPEC.md §9 rule 3 is
 * enforced by ``_traceable`` below: no verdict may exist without either cited
 * evidence or a stated reason for its absence.
 */
export interface MatchResult {
  confidence: number;
  /**
   * Evidence.id values supporting this verdict. Must be empty when verdict is 'missing'.
   */
  evidence_ids?: string[];
  /**
   * Required when verdict is 'missing'. Rendered as the explicit 'why not' line.
   */
  missing_reason?: string | null;
  /**
   * One sentence, English. Displayed under the expanded requirement row.
   */
  reasoning: string;
  requirement_id: string;
  verdict: "proven" | "partial" | "missing";
}
export interface Resume {
  /**
   * One paragraph. May be empty.
   */
  candidate_summary?: string;
  education?: Education[];
  evidence?: Evidence[];
  /**
   * Paid employment only. A fresh graduate is 0.0 and that is fine.
   */
  total_years_work?: number;
}
export interface Education {
  degree: string;
  /**
   * Free text on purpose — '3.5+', '2:1', 'First Class' are all real.
   */
  gpa?: string | null;
  institution: string;
  year?: number | null;
}
/**
 * One thing the candidate has actually done.
 *
 * F4 is the whole project: a fresh graduate has no employment bullet points, so
 * coursework, projects and part-time work must be first-class evidence records
 * rather than second-class text.
 */
export interface Evidence {
  duration_months?: number | null;
  evidence_type:
    | "employment"
    | "internship"
    | "part_time"
    | "coursework"
    | "project"
    | "volunteer"
    | "certification"
    | "competition";
  /**
   * Stable within one resume: e1, e2, … Cited by MatchResult.evidence_ids and facts_used.
   */
  id: string;
  outcome?: string | null;
  skills?: string[];
  /**
   * Verbatim line from the resume. The results screen highlights this exact string, and the F5 rewrite validator checks generated claims against it.
   */
  source_line: string;
  team_size?: number | null;
}
