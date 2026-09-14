import * as React from "react";

import { cn } from "@/lib/utils";

export type CardPadding = "none" | "sm" | "md" | "lg";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Optional header slot, separated by a rule. Any label is a caller prop. */
  header?: React.ReactNode;
  /** Optional footer slot on a muted ground. */
  footer?: React.ReactNode;
  padding?: CardPadding;
  /** Adds a hover affordance for cards that are themselves a link target. */
  interactive?: boolean;
  /** Classes for the body wrapper only, leaving the card frame untouched. */
  bodyClassName?: string;
}

const PADDING: Record<CardPadding, string> = {
  none: "",
  sm: "p-3",
  md: "p-5",
  lg: "p-6 sm:p-8",
};

/* Header and footer use the same horizontal rhythm as the body but a tighter
   vertical one, so the rules sit close to their content. */
const BAND_PADDING: Record<CardPadding, string> = {
  none: "",
  sm: "px-3 py-2",
  md: "px-5 py-3",
  lg: "px-6 py-4 sm:px-8",
};

/**
 * Padded surface with optional header/footer bands.
 *
 * No `overflow-hidden` on the frame: it would clip the 2px focus outline of any
 * control sitting flush against the card edge.
 */
export const Card = React.forwardRef<HTMLDivElement, CardProps>(function Card(
  {
    header,
    footer,
    padding = "md",
    interactive = false,
    bodyClassName,
    className,
    children,
    ...rest
  },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        "rounded-card border border-rule bg-surface-raised text-ink",
        interactive && "transition-colors duration-150 hover:bg-paper-2",
        className,
      )}
      {...rest}
    >
      {header ? (
        <div className={cn("border-b border-rule", BAND_PADDING[padding])}>
          {header}
        </div>
      ) : null}

      <div className={cn(PADDING[padding], bodyClassName)}>{children}</div>

      {footer ? (
        <div
          className={cn("border-t border-rule bg-paper-2", BAND_PADDING[padding])}
        >
          {footer}
        </div>
      ) : null}
    </div>
  );
});
