"use client";

import Link from "next/link";

export interface UpgradePromptProps {
  message?: string;
  onDismiss?: () => void;
}

export function UpgradePrompt({ message, onDismiss }: UpgradePromptProps) {
  return (
    <div
      role="alert"
      data-testid="upgrade-prompt"
      className="rounded-2xl border border-accent/40 bg-accent-tint/55 p-5 text-sm text-ink"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-serif text-base font-bold text-ink">
            Plan quota reached
          </p>
          <p className="mt-1 text-ink-2">
            {message ||
              "You have used all credits included in your current plan. Upgrade to the 30-day Job Hunt Pass for 50 analyses, 30 AI rewrites, and 10 saved resumes."}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2.5">
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-lg border border-rule bg-surface-raised px-3 py-2 text-xs font-medium text-ink-2 hover:bg-paper-2"
            >
              Dismiss
            </button>
          )}
          <Link
            href="/pricing?plan=pass"
            className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-surface-raised hover:bg-accent-2"
          >
            Upgrade on Pricing ↗
          </Link>
        </div>
      </div>
    </div>
  );
}

