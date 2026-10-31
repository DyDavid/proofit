import type { Metadata } from "next";
import { ResultsById } from "@/components/results/ResultsById";
import { ResultsView } from "@/components/results/ResultsView";
import { sampleBaseline } from "@/lib/fixtures/sample-baseline";
import { sampleMatch } from "@/lib/fixtures/sample-match";

export const metadata: Metadata = {
  title: "Match Result",
  description: "Requirement-by-requirement resume coverage report.",
  robots: {
    index: false,
    follow: false,
  },
};

export interface ResultsPageProps {
  searchParams: Promise<{ id?: string }>;
}

/**
 * Results. Two paths:
 *  - no `?id=` — the static "try a sample analysis" fixture (Landing's
 *    secondary CTA links straight here), rendered synchronously server-side,
 *    paired with its own hand-authored `sampleBaseline` fixture.
 *  - `?id=` — a real (mock-mode) analysis, fetched client-side by
 *    `ResultsById` via `lib/api.ts` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).
 * The hidden-strengths section is still Phase 4 scope.
 */
export default async function ResultsPage({ searchParams }: ResultsPageProps) {
  const { id } = await searchParams;

  if (id) {
    return <ResultsById id={id} />;
  }

  return <ResultsView match={sampleMatch} baseline={sampleBaseline} />;
}
