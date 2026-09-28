import * as React from "react";

import Link from "next/link";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "invert";
export type ButtonSize = "sm" | "md" | "lg";
/** `"arrow"` appends the source design's sliding double-arrow circle — only
 * for a true "go forward" call to action (upload, run match), never for
 * every button. Ignored on `variant="ghost"`, which never carries an icon. */
export type ButtonIcon = "none" | "arrow";

interface ButtonOwnProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ButtonIcon;
  /** Shows a spinner, sets aria-busy, and blocks activation. */
  loading?: boolean;
  fullWidth?: boolean;
  className?: string;
  children?: React.ReactNode;
}

export type ButtonAsButtonProps = ButtonOwnProps &
  Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, keyof ButtonOwnProps> & {
    as?: "button";
  };

export type ButtonAsAnchorProps = ButtonOwnProps &
  Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, keyof ButtonOwnProps> & {
    as: "a";
    href: string;
  };

/** Either a real `<button>` or, with `as="a"`, an anchor styled identically. */
export type ButtonProps = ButtonAsButtonProps | ButtonAsAnchorProps;

/*
 * leading-[1.6] rather than leading-none: a wrapped label clips at tight line
 * heights. The focus ring is an outline so it traces the control's own
 * radius; the base layer in globals.css sets the same ring globally, these
 * utilities just make the intent local and explicit.
 */
const BASE = cn(
  "inline-flex items-center justify-center gap-2",
  "rounded-pill border font-medium leading-[1.6] no-underline",
  "transition-colors duration-150 select-none",
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
  "disabled:cursor-not-allowed disabled:opacity-55",
  "aria-disabled:cursor-not-allowed aria-disabled:opacity-55",
);

const VARIANT: Record<ButtonVariant, string> = {
  primary: "border-accent bg-accent text-paper hover:bg-accent-2 active:bg-accent-2",
  secondary: "border-ink bg-ink text-paper hover:bg-ink-2 active:bg-ink-2",
  ghost:
    "border-rule-2 bg-transparent text-ink hover:border-accent hover:text-accent",
  danger: "border-danger-2 bg-danger-2 text-paper hover:bg-danger active:bg-danger",
  /** The design's `.cta-ink`: an inverted CTA for use on an accent-coloured
   * band, where a plain `primary` button would disappear into the ground. */
  invert: "border-paper bg-paper text-accent hover:bg-accent-tint active:bg-accent-tint",
};

/* min-h + py, never a fixed h-*, so a wrapped label grows the control
   instead of overflowing it. Nothing drops to text-xs. Padding on the right
   is tighter when an arrow-icon circle is present (it supplies its own
   inset), matching the source design's `.cta` (`padding: 0 6px 0 20px`). */
const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3 py-1.5 text-sm",
  md: "min-h-11 px-4 py-2 text-base",
  lg: "min-h-14 px-6 py-3 text-lg",
};

const SIZE_WITH_ARROW: Record<ButtonSize, string> = {
  sm: "min-h-9 py-1.5 pl-3 pr-1.5 text-sm",
  md: "min-h-11 py-2 pl-4 pr-2 text-base",
  lg: "min-h-14 py-3 pl-6 pr-2 text-lg",
};

const ARROW_CIRCLE_SIZE: Record<ButtonSize, string> = {
  sm: "size-6",
  md: "size-8",
  lg: "size-9",
};

/* Fixed pixel sizes for the arrow glyph + its travel distance, matching
   each ARROW_CIRCLE_SIZE above (size-6/8/9 = 24/32/36px). The travel must
   clear the circle's own diameter or both arrows show at once (a
   percentage-based translate — relative to the glyph's own tiny box, not
   the circle — was tried first and didn't clear it). */
const ARROW_GLYPH_PX: Record<ButtonSize, number> = { sm: 9, md: 12, lg: 14 };
const ARROW_TRAVEL_PX: Record<ButtonSize, number> = { sm: 22, md: 30, lg: 34 };

function Spinner() {
  return (
    <svg
      className="animate-spin shrink-0"
      width="1.15em"
      height="1.15em"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="2.5"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ArrowGlyph({ size, variant }: { size: number; variant: "a" | "b" }) {
  return (
    <svg
      className={variant === "a" ? "arrow-glyph-a" : "arrow-glyph-b"}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  );
}

/** The circle's own colours are always the button's bg/text swapped, so the
 * arrow reads clearly against whichever surface the button sits on. */
const ARROW_CIRCLE_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-paper text-accent",
  secondary: "bg-paper text-ink",
  ghost: "",
  danger: "bg-paper text-danger-2",
  invert: "bg-accent text-paper",
};

/** The circular icon-in-a-circle at the end of a `.cta`-style button: two
 * overlapping arrows that swap places on hover/focus, so the arrow appears
 * to travel continuously to the right, matching the source design's `.ab`. */
function ArrowCircle({ size, variant }: { size: ButtonSize; variant: ButtonVariant }) {
  return (
    <span
      className={cn(
        "relative shrink-0 overflow-hidden rounded-full",
        ARROW_CIRCLE_SIZE[size],
        ARROW_CIRCLE_VARIANT[variant],
      )}
      style={{ "--arrow-travel": `${ARROW_TRAVEL_PX[size]}px` } as React.CSSProperties}
      aria-hidden="true"
    >
      <ArrowGlyph size={ARROW_GLYPH_PX[size]} variant="a" />
      <ArrowGlyph size={ARROW_GLYPH_PX[size]} variant="b" />
    </span>
  );
}

/**
 * The one button in the app. Carries no text of its own — every label is a
 * child supplied by the caller through `t()`.
 */
export const Button = React.forwardRef<
  HTMLButtonElement | HTMLAnchorElement,
  ButtonProps
>(function Button(props, ref) {
  if (props.as === "a") {
    const {
      as: _as,
      variant = "primary",
      size = "md",
      icon = "none",
      loading = false,
      fullWidth = false,
      className,
      children,
      ...anchorProps
    } = props;
    void _as;
    const showArrow = icon === "arrow" && variant !== "ghost" && !loading;

    return (
      <Link
        ref={ref as React.ForwardedRef<HTMLAnchorElement>}
        className={cn(
          "group",
          BASE,
          VARIANT[variant],
          showArrow ? SIZE_WITH_ARROW[size] : SIZE[size],
          fullWidth && "w-full",
          // An anchor cannot be `disabled`; neutralise it instead.
          loading && "pointer-events-none",
          className,
        )}
        aria-busy={loading || undefined}
        aria-disabled={loading || undefined}
        {...anchorProps}
      >
        {loading ? <Spinner /> : null}
        {children}
        {showArrow ? <ArrowCircle size={size} variant={variant} /> : null}
      </Link>
    );
  }

  const {
    as: _as,
    variant = "primary",
    size = "md",
    icon = "none",
    loading = false,
    fullWidth = false,
    className,
    children,
    disabled,
    type = "button",
    ...buttonProps
  } = props;
  void _as;
  const showArrow = icon === "arrow" && variant !== "ghost" && !loading;

  return (
    <button
      ref={ref as React.ForwardedRef<HTMLButtonElement>}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "group",
        BASE,
        VARIANT[variant],
        showArrow ? SIZE_WITH_ARROW[size] : SIZE[size],
        fullWidth && "w-full",
        className,
      )}
      {...buttonProps}
    >
      {loading ? <Spinner /> : null}
      {children}
      {showArrow ? <ArrowCircle size={size} variant={variant} /> : null}
    </button>
  );
});
