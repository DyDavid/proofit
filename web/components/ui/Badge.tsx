import * as React from "react";

import { cn } from "@/lib/utils";

export type BadgeTone = "lac" | "muted" | "proven" | "partial" | "missing";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

/**
 * Small mono-uppercase tinted tag (BRAND.md §3's "verdict pill" pattern —
 * the reference's `.vd`/`.chip` style). Text-only by default — pair with
 * `VerdictIcon` when the content is a verdict, never colour alone.
 */
export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  function Badge({ tone = "muted", className, children, ...rest }, ref) {
    return (
      <span
        ref={ref}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-tag px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide",
          tone === "lac" && "bg-lac-tint text-lac",
          tone === "muted" && "bg-paper-3 text-ink-2",
          tone === "proven" && "bg-proven-tint text-proven",
          tone === "partial" && "bg-partial-tint text-partial-ink",
          tone === "missing" && "bg-missing-tint text-missing",
          className,
        )}
        {...rest}
      >
        {children}
      </span>
    );
  },
);
