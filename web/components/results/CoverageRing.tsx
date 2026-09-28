"use client";

import { useCountUp, useInView } from "@/lib/useInView";
import type { CoverageTile } from "@/components/results/CoverageStat";

const RADIUS = 70;
const STROKE = 14;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The Results header's primary coverage stat: a donut ring (proven + partial
 * arcs, sized by their share of requirements, matching the source design's
 * gauge) with a count-up percentage in the centre and a slow-spinning
 * decorative dashed outer ring, all triggered once the ring scrolls into
 * view (`useInView`/`useCountUp` — see lib/useInView.ts).
 */
export function CoverageRing({
  value,
  tiles,
  label,
}: {
  value: number;
  tiles: CoverageTile[];
  label: string;
}) {
  const { ref, inView } = useInView<HTMLDivElement>(0.4);
  const count = useCountUp(Math.round(value), inView, { duration: 1400, delay: 200 });

  const total = tiles.length || 1;
  const provenLen = (tiles.filter((t) => t.verdict === "proven").length / total) * CIRCUMFERENCE;
  const partialLen = (tiles.filter((t) => t.verdict === "partial").length / total) * CIRCUMFERENCE;
  const provenOffset = 0;
  const partialOffset = provenLen;

  return (
    <div ref={ref} className="relative mx-auto size-52 shrink-0 sm:size-60">
      <svg viewBox="0 0 160 160" className="absolute inset-0" aria-hidden="true">
        <circle
          cx="80"
          cy="80"
          r="77"
          fill="none"
          stroke="var(--color-rule)"
          strokeWidth="1"
          strokeDasharray="2 9"
          className="motion-safe:animate-badge-spin origin-center [animation-duration:50s]"
        />
      </svg>

      <svg viewBox="0 0 160 160" className="absolute inset-0 -rotate-90" role="img" aria-label={label}>
        <circle cx="80" cy="80" r={RADIUS} fill="none" stroke="var(--color-track)" strokeWidth={STROKE} />
        {provenLen > 0 ? (
          <circle
            cx="80"
            cy="80"
            r={RADIUS}
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${Math.max(provenLen - 2, 0)} ${CIRCUMFERENCE}`}
            strokeDashoffset={-provenOffset}
          />
        ) : null}
        {partialLen > 0 ? (
          <circle
            cx="80"
            cy="80"
            r={RADIUS}
            fill="none"
            stroke="var(--color-ink)"
            strokeOpacity="0.55"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${Math.max(partialLen - 2, 0)} ${CIRCUMFERENCE}`}
            strokeDashoffset={-partialOffset}
          />
        ) : null}
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="font-serif text-5xl font-extrabold tabular-nums sm:text-6xl">
          {count}
          <span className="text-[0.5em] text-accent">%</span>
        </div>
        <p className="mt-2 text-center font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
          {label}
        </p>
      </div>
    </div>
  );
}
