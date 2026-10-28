"use client";

import type { PlanDefinition } from "@/lib/billing/api";

export interface PricingCardProps {
  plan: PlanDefinition;
  ctaLabel: string;
  disabled?: boolean;
  showArrow?: boolean;
  activeUntilText?: string | null;
  onAction: () => void;
}

export function PricingCard({
  plan,
  ctaLabel,
  disabled = false,
  showArrow = true,
  activeUntilText = null,
  onAction,
}: PricingCardProps) {
  const limitRows = [
    { label: "Analyses", value: plan.limits.analyses_label },
    { label: "AI rewrites", value: plan.limits.rewrites_label },
    { label: "Saved resumes", value: plan.limits.saved_resumes_label },
    { label: "Support", value: plan.limits.support_label },
  ];

  return (
    <div
      data-testid={`pricing-card-${plan.id}`}
      className={`flex h-full flex-col rounded-2xl border p-1.5 transition-shadow ${
        plan.recommended
          ? "border-accent/45 bg-accent-tint/40 shadow-sm"
          : "border-rule-2 bg-paper-2/75"
      }`}
    >
      {/* Inner panel */}
      <div className="flex flex-1 flex-col rounded-xl border border-rule bg-surface-raised">
        {/* Header block */}
        <div className="p-6">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-medium text-ink">{plan.name}</h2>
            {plan.recommended && (
              <span className="rounded-md bg-accent-tint px-2.5 py-1 text-sm font-medium text-accent">
                Recommended
              </span>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-baseline gap-2">
            <span className="font-serif text-3xl font-semibold tracking-tight text-ink">
              {plan.price_display}
            </span>
            <span className="text-sm text-ink-3">{plan.price_suffix}</span>
          </div>

          {activeUntilText && (
            <p
              data-testid={`pricing-active-until-${plan.id}`}
              className="mt-1.5 text-xs font-medium text-accent"
            >
              {activeUntilText}
            </p>
          )}

          <p className="mt-3 text-sm leading-relaxed text-ink-2">
            {plan.description}
          </p>
        </div>

        {/* Divider + Limits list (flex-1 so feature checklists align at bottom across cards) */}
        <div className="flex flex-1 flex-col border-t border-rule px-6">
          <dl className="divide-y divide-rule text-sm">
            {limitRows.map((row) => (
              <div
                key={row.label}
                className="flex items-center justify-between gap-4 py-4"
              >
                <dt className="text-ink-3">{row.label}</dt>
                <dd className="text-right font-medium text-ink">{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* Divider + Features checklist */}
        <div className="border-t border-rule p-6">
          <ul className="space-y-3 text-sm text-ink-2">
            {plan.features.map((feature) => (
              <li key={feature} className="flex items-start gap-2.5">
                <svg
                  className="mt-0.5 h-4 w-4 shrink-0 text-accent"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.415 0l-3.5-3.5a1 1 0 111.414-1.42l2.793 2.794 6.793-6.794a1 1 0 011.415 0z"
                    clipRule="evenodd"
                  />
                </svg>
                <span>{feature}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* CTA button sits inside the outer frame, below the inner panel */}
      <button
        type="button"
        disabled={disabled}
        aria-disabled={disabled}
        onClick={disabled ? undefined : onAction}
        data-testid={`pricing-cta-${plan.id}`}
        className={`mt-1.5 flex h-12 w-full items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors ${
          disabled
            ? "cursor-not-allowed bg-paper-3 text-ink-3"
            : plan.recommended
              ? "cursor-pointer bg-accent text-surface-raised hover:bg-accent-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              : "cursor-pointer bg-ink text-surface-raised hover:bg-ink-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        }`}
      >
        <span>{ctaLabel}</span>
        {!disabled && showArrow && (
          <span aria-hidden="true" className="text-base leading-none">
            ↗
          </span>
        )}
      </button>
    </div>
  );
}

