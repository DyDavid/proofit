"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface CampusContactDialogProps {
  open: boolean;
  onClose: () => void;
  email?: string;
}

const FOCUSABLE =
  'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

export function CampusContactDialog({
  open,
  onClose,
  email = "dydavid168@gmail.com",
}: CampusContactDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => setMounted(true), []);

  // Lock body scroll while modal is open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Keyboard accessibility: Escape to close & focus trapping
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  // Focus modal on open
  useEffect(() => {
    if (open && dialogRef.current) {
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (focusable.length > 0) {
        focusable[0].focus();
      }
    }
  }, [open]);

  if (!mounted || !open) return null;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(email);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback if clipboard API unavailable
    }
  }

  const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(
    email,
  )}&su=${encodeURIComponent("Proofit Campus Inquiry")}`;

  const mailtoUrl = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(
    "Proofit Campus Inquiry",
  )}`;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="campus-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
    >
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-ink/50 backdrop-blur-xs transition-opacity"
      />

      {/* Dialog Card */}
      <div
        ref={dialogRef}
        className="relative z-10 w-full max-w-md rounded-2xl border border-rule bg-surface-raised p-6 shadow-2xl transition-all sm:p-7"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-rule pb-4">
          <div>
            <span className="inline-flex items-center rounded-pill bg-accent-tint px-2.5 py-0.5 font-mono text-xs font-semibold uppercase tracking-wider text-accent">
              Campus Inquiry
            </span>
            <h2
              id="campus-dialog-title"
              className="mt-2 font-serif text-xl font-bold tracking-tight text-ink sm:text-2xl"
            >
              Partner with Proofit
            </h2>
            <p className="mt-1 text-xs text-ink-2">
              For universities, career centres, and student cohorts.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="cursor-pointer rounded-full p-1.5 text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="mt-5 space-y-4">
          <p className="text-sm leading-relaxed text-ink-2">
            Reach out directly to discuss cohort onboarding, tailored campus licensing, or dedicated career support dashboards.
          </p>

          {/* Email Box */}
          <div className="flex items-center justify-between gap-3 rounded-xl border border-rule bg-paper/70 p-3.5">
            <div className="min-w-0">
              <p className="font-mono text-[11px] uppercase tracking-wider text-ink-3">
                Direct Contact
              </p>
              <p className="select-all truncate font-mono text-sm font-semibold text-ink">
                {email}
              </p>
            </div>
            <button
              type="button"
              onClick={handleCopy}
              className={`inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all active:scale-95 ${
                copied
                  ? "border-emerald-600 bg-emerald-50 text-emerald-700"
                  : "border-rule bg-surface-raised text-ink shadow-2xs hover:border-accent hover:text-accent"
              }`}
            >
              {copied ? (
                <>
                  <svg className="h-3.5 w-3.5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                    />
                  </svg>
                  <span>Copy</span>
                </>
              )}
            </button>
          </div>

          {/* Action Links */}
          <div className="grid grid-cols-1 gap-2.5 pt-2 sm:grid-cols-2">
            <a
              href={gmailUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-accent-2 active:scale-95"
            >
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.272H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
              </svg>
              <span>Open in Gmail ↗</span>
            </a>

            <a
              href={mailtoUrl}
              className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-rule bg-paper-2 px-4 py-2.5 text-xs font-semibold text-ink transition-all hover:bg-paper active:scale-95"
            >
              <span>Default mail app ↗</span>
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 border-t border-rule pt-4 text-center">
          <button
            type="button"
            onClick={onClose}
            className="cursor-pointer text-xs font-medium text-ink-3 transition-colors hover:text-ink hover:underline"
          >
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

