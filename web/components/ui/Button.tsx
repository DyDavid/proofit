import * as React from "react";

import { Link } from "@/i18n/routing";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonOwnProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
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
 * leading-[1.6] rather than leading-none: Khmer stacks subscript consonants
 * below the baseline and clips at tight line heights (PERSON_B_PLAN_v2.md §7.4).
 * The focus ring is an outline so it traces the control's own radius; the base
 * layer in globals.css sets the same ring globally, these utilities just make
 * the intent local and explicit.
 */
const BASE = cn(
  "inline-flex items-center justify-center gap-2",
  "rounded-pill border font-medium leading-[1.6] no-underline",
  "transition-colors duration-150 select-none",
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lac",
  "disabled:cursor-not-allowed disabled:opacity-55",
  "aria-disabled:cursor-not-allowed aria-disabled:opacity-55",
);

const VARIANT: Record<ButtonVariant, string> = {
  primary: "border-lac bg-lac text-paper hover:bg-lac-2 active:bg-lac-2",
  secondary: "border-ink bg-ink text-paper hover:bg-ink-2 active:bg-ink-2",
  ghost:
    "border-transparent bg-transparent text-ink hover:bg-paper-2 active:bg-paper-2",
  danger: "border-lac-2 bg-lac-2 text-paper hover:bg-lac active:bg-lac",
};

/* min-h + py, never a fixed h-*, so a wrapped Khmer label grows the control
   instead of overflowing it. Nothing drops to text-xs. */
const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3 py-1.5 text-sm",
  md: "min-h-11 px-4 py-2 text-base",
  lg: "min-h-14 px-6 py-3 text-lg",
};

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

/**
 * The one button in the app. Carries no text of its own — every label is a
 * child supplied by the caller through next-intl `t()`.
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
      loading = false,
      fullWidth = false,
      className,
      children,
      ...anchorProps
    } = props;
    void _as;

    return (
      <Link
        ref={ref as React.ForwardedRef<HTMLAnchorElement>}
        className={cn(
          BASE,
          VARIANT[variant],
          SIZE[size],
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
      </Link>
    );
  }

  const {
    as: _as,
    variant = "primary",
    size = "md",
    loading = false,
    fullWidth = false,
    className,
    children,
    disabled,
    type = "button",
    ...buttonProps
  } = props;
  void _as;

  return (
    <button
      ref={ref as React.ForwardedRef<HTMLButtonElement>}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        BASE,
        VARIANT[variant],
        SIZE[size],
        fullWidth && "w-full",
        className,
      )}
      {...buttonProps}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
});
