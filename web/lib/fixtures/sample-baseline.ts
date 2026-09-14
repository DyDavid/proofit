import type { BaselineMatch } from "@/lib/types";

/**
 * Paired with `sampleMatch` (same requirement ids), built by the same
 * token-overlap rule as the mock-mode fixtures (data/fixtures/*.baseline.json)
 * — see docs/superpowers/plans/2026-09-14-phase-2-results-experience.md Task 3.
 *
 * Per requirement: lowercase-token overlap between the requirement's `text`
 * and the *cited* evidence only — the `source_line` of every evidence id the
 * real `sampleMatch.results` entry lists, or `resume.education` for the
 * education row (r6) that carries no cited evidence id. Structured fields
 * like an evidence record's `skills` tag are deliberately out of scope, same
 * as the backend `data/fixtures/*.baseline.json` precedent (see e.g.
 * `fresh_grad_stretch.baseline.json`'s r6, scored `missing` even though its
 * cited evidence's `skills` array names "Git" — only literal prose counts).
 * The matcher never sees the real verdict or reasoning, and never sees
 * anything but that one field's literal text.
 *
 * coverage_score = weighted (proven=1, partial=0.5, missing=0; required
 * weight 1, preferred weight 0.5) as a % of total weight:
 *   required (r1,r2,r4,r5,r8,r9): 0+0+0.5+0.5+0.5+0 = 1.5 / 6
 *   preferred (r3,r6,r7,r10,r11,r12): 0+0+0+0+1+0 = 1.0 / 6 (raw) → 0.5 / 3 (weighted)
 *   (1.5 + 0.5) / 9 * 100 = 22.2
 * `sampleMatch.coverage_score` is 55.6 under that same formula applied to its
 * own results — 5/9 of the total weight against this file's 2/9 — so the gap
 * is 33.3 points. There is no test enforcing any particular gap for this file
 * (unlike the backend fixtures' `tests/test_baseline_fixtures.py`); this
 * number is whatever the rule, applied honestly and consistently, produces.
 */
export const sampleBaseline: BaselineMatch = {
  coverage_score: 22.2,
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
      verdict: "partial",
      score: 0.3,
      matched_terms: ["team"],
    },
    {
      requirement_id: "r9",
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
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
      verdict: "missing",
      score: 0.0,
      matched_terms: [],
    },
  ],
};
