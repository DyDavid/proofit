import type { BaselineMatch } from "@/lib/types";

/**
 * Paired with `sampleMatch` (same requirement ids), built by the same
 * token-overlap rule as the mock-mode fixtures (data/fixtures/*.baseline.json)
 * — see docs/superpowers/plans/2026-09-14-phase-2-results-experience.md Task 3.
 *
 * Per requirement: lowercase-token overlap between the requirement's `text`
 * and the *cited* evidence only — the `source_line` of every evidence id the
 * real `sampleMatch.results` entry lists (plus that evidence's `skills` tags,
 * since a naive keyword matcher indexes an explicit skill tag at least as
 * readily as free prose), or `resume.education` for the education/language
 * rows (r6, r11) that carry no cited evidence id. The matcher never sees the
 * real verdict or reasoning — only what's literally spelled out in that text.
 *
 * coverage_score = weighted (proven=1, partial=0.5, missing=0; required
 * weight 1, preferred weight 0.5) as a % of total weight:
 *   required (r1,r2,r4,r5,r8,r9): 0+0+0.5+0.5+1+1 = 3.0 / 6
 *   preferred (r3,r6,r7,r10,r11,r12): 0+0+0+0+0.5+0.5 = 1.0 / 3 (weighted)
 *   (3.0 + 1.0) / 9 * 100 = 44.4
 * sampleMatch.coverage_score is 68 → a 23.6-point gap (within the 10–35
 * credible-comparison range Task 3's fixture test enforces on the backend).
 */
export const sampleBaseline: BaselineMatch = {
  coverage_score: 44.4,
  method: "tfidf",
  results: [
    {
      requirement_id: "r1",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r2",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r3",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r4",
      verdict: "partial",
      score: 0.32,
      matched_terms: ["rest"],
    },
    {
      requirement_id: "r5",
      verdict: "partial",
      score: 0.3,
      matched_terms: ["systems"],
    },
    {
      requirement_id: "r6",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r7",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r8",
      verdict: "proven",
      score: 0.68,
      matched_terms: ["git", "team"],
    },
    {
      requirement_id: "r9",
      verdict: "proven",
      score: 0.6,
      matched_terms: ["python"],
    },
    {
      requirement_id: "r10",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
    {
      requirement_id: "r11",
      verdict: "proven",
      score: 0.85,
      matched_terms: ["khmer", "english"],
    },
    {
      requirement_id: "r12",
      verdict: "proven",
      score: 0.6,
      matched_terms: ["sql"],
    },
  ],
};
