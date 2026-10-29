"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface CampusContactDialogProps {
  open: boolean;
  onClose: () => void;
  email?: string;
}

const DEFAULT_CONTACT_EMAIL = "dydavid168@gmail.com";
const INQUIRY_SUBJECT = "Proofit Campus Partnership Inquiry";
const INQUIRY_BODY_TEMPLATE = `Hi David,

I am reaching out regarding Proofit Campus for our students and cohorts.

Institution: [Your University / Institution]
Estimated Cohort Size: [e.g. 50 students]
Target Timeline: [e.g. Next Semester]

We would love to discuss campus licensing, cohort onboarding, and career center tools.

Best regards,`;

const FOCUSABLE =
  'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

export function CampusContactDialog({
  open,
  onClose,
  email,
}: CampusContactDialogProps) {
  const contactEmail =
    email ||
    process.env.NEXT_PUBLIC_CAMPUS_CONTACT_EMAIL ||
    DEFAULT_CONTACT_EMAIL;

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [mounted, setMounted] = useState(false);
  const [emailCopied, setEmailCopied] = useState(false);
  const [draftCopied, setDraftCopied] = useState(false);

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

  async function handleCopyEmail() {
    try {
      await navigator.clipboard.writeText(contactEmail);
      setEmailCopied(true);
      setTimeout(() => setEmailCopied(false), 2000);
    } catch {
      // Clipboard unavailable
    }
  }

  async function handleCopyDraft() {
    try {
      await navigator.clipboard.writeText(INQUIRY_BODY_TEMPLATE);
      setDraftCopied(true);
      setTimeout(() => setDraftCopied(false), 2000);
    } catch {
      // Clipboard unavailable
    }
  }

  const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(
    contactEmail,
  )}&su=${encodeURIComponent(INQUIRY_SUBJECT)}&body=${encodeURIComponent(
    INQUIRY_BODY_TEMPLATE,
  )}`;

  const mailtoUrl = `mailto:${encodeURIComponent(
    contactEmail,
  )}?subject=${encodeURIComponent(INQUIRY_SUBJECT)}&body=${encodeURIComponent(
    INQUIRY_BODY_TEMPLATE,
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
        className="relative z-10 w-full max-w-lg rounded-3xl border border-rule bg-surface-raised p-6 shadow-2xl transition-all sm:p-7"
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-rule pb-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent-tint px-3 py-1 font-mono text-xs font-semibold text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
              Campus Partnership
            </div>
            <h2
              id="campus-dialog-title"
              className="mt-3 font-serif text-2xl font-bold tracking-tight text-ink sm:text-3xl"
            >
              Partner with Proofit
            </h2>
            <p className="mt-1 text-xs text-ink-2 sm:text-sm">
              Connect directly to arrange cohort access, tailored campus pricing, and career center tools.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="cursor-pointer rounded-full p-2 text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent active:scale-95"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="mt-5 space-y-4">
          {/* Email Box */}
          <div className="flex flex-col gap-3 rounded-2xl border border-rule bg-paper p-4 shadow-2xs sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-rule bg-surface-raised text-accent shadow-2xs">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <div className="min-w-0">
                <p className="font-mono text-[11px] font-medium uppercase tracking-wider text-ink-3">
                  Direct Inquiries
                </p>
                <p className="select-all truncate font-mono text-sm font-bold text-ink sm:text-[15px]">
                  {contactEmail}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleCopyEmail}
              className={`inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-all active:scale-95 ${
                emailCopied
                  ? "border-emerald-600 bg-emerald-50 text-emerald-700 shadow-2xs"
                  : "border-rule bg-surface-raised text-ink shadow-2xs hover:border-accent hover:text-accent"
              }`}
            >
              {emailCopied ? (
                <>
                  <svg className="h-3.5 w-3.5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
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
                  <span>Copy Email</span>
                </>
              )}
            </button>
          </div>

          {/* Draft Preview Box */}
          <div className="rounded-2xl border border-rule bg-white/70 p-3.5">
            <div className="flex items-center justify-between text-xs font-semibold text-ink-2">
              <span className="flex items-center gap-1.5">
                <svg className="h-3.5 w-3.5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Pre-filled Draft Ready
              </span>
              <button
                type="button"
                onClick={handleCopyDraft}
                className="cursor-pointer font-mono text-[11px] text-accent transition-colors hover:underline hover:text-accent-2"
              >
                {draftCopied ? "✓ Draft Copied!" : "Copy Template"}
              </button>
            </div>
            <div className="mt-2 rounded-xl border border-rule/80 bg-paper/80 p-2.5 font-mono text-[11px] leading-relaxed text-ink-3 select-all whitespace-pre-line sm:text-xs">
              {INQUIRY_BODY_TEMPLATE}
            </div>
          </div>

          {/* Action Links */}
          <div className="grid grid-cols-1 gap-2.5 pt-1 sm:grid-cols-2">
            <a
              href={gmailUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-accent-2 active:scale-95"
            >
              <svg className="h-4 w-4 shrink-0" fill="currentColor" viewBox="0 0 24 24">
                <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.272H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
              </svg>
              <span>Open in Gmail (Draft ready) ↗</span>
            </a>

            <a
              href={mailtoUrl}
              className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-rule bg-paper-2 px-4 py-3 text-xs font-semibold text-ink transition-all hover:bg-paper active:scale-95 shadow-2xs"
            >
              <span>Default mail app ↗</span>
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-5 border-t border-rule pt-3 text-center">
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
