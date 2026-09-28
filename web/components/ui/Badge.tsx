import * as React from "react";

import { cn } from "@/lib/utils";

export type BadgeTone = "accent" | "muted" | "proven" | "partial" | "missing";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

/**
 * Small mono-uppercase pill tag, matching the source design's verdict chips:
 * `proven` is a solid accent fill, `partial`/`missing` are outline-only (one
 * solid, one dashed) rather than tinted like the other tones. Text-only by
 * default — pair with `VerdictIcon` when the content is a verdict, never
 * colour alone.
 */
export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  function Badge({ tone = "muted", className, children, ...rest }, ref) {
    return (
      <span
        ref={ref}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-tag px-2.5 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide",
          tone === "accent" && "bg-accent-tint text-accent",
          tone === "muted" && "bg-paper-3 text-ink-2",
          tone === "proven" && "bg-proven text-paper",
          tone === "partial" &&
            "border border-partial-ink text-partial-ink",
          tone === "missing" && "border border-dashed border-missing text-missing",
          className,
        )}
        {...rest}
      >
        {children}
      </span>
    );
  },
);
