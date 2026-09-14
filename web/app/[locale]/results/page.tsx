import { ResultsById } from "@/components/results/ResultsById";
import { ResultsView } from "@/components/results/ResultsView";
import { sampleMatch } from "@/lib/fixtures/sample-match";

export interface ResultsPageProps {
  searchParams: Promise<{ id?: string }>;
}

/**
 * Results. Two paths:
 *  - no `?id=` — the static "try a sample analysis" fixture (Landing's
 *    secondary CTA links straight here), rendered synchronously server-side.
 *  - `?id=` — a real (mock-mode) analysis, fetched client-side by
 *    `ResultsById` via `lib/api.ts` (PERSON_B_PLAN_v2.md §5 Phase 1 task 4).
 * The baseline-comparison toggle and hidden-strengths section are Phase 2 /
 * Phase 4 scope.
 */
export default async function ResultsPage({ searchParams }: ResultsPageProps) {
  const { id } = await searchParams;

  if (id) {
    return <ResultsById id={id} />;
  }

  return <ResultsView match={sampleMatch} />;
}
