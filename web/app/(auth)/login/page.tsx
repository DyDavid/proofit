"use client";

import * as React from "react";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { TurnstileWidget, isTurnstileConfigured } from "@/components/auth/TurnstileWidget";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { createClient } from "@/lib/supabase/client";

function sanitizeNextPath(raw: string | null): string {
  if (!raw) return "/analyze";
  const trimmed = raw.trim();
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    return trimmed;
  }
  return "/analyze";
}

function mapAuthError(err: unknown): string {
  const msg =
    err && typeof err === "object" && "message" in err && typeof err.message === "string"
      ? err.message.toLowerCase()
      : "";
  const status =
    err && typeof err === "object" && "status" in err && typeof err.status === "number"
      ? err.status
      : undefined;

  if (status === 429 || msg.includes("rate limit") || msg.includes("too many") || msg.includes("security purposes")) {
    return "Too many attempts. Please wait a minute before trying again.";
  }
  if (msg.includes("invalid login credentials") || msg.includes("invalid credentials")) {
    return "Invalid email or password. Please check your credentials or create an account.";
  }
  if (msg.includes("email not confirmed")) {
    return "Your email is not confirmed yet. Please check your inbox and click the activation link.";
  }
  if (msg.includes("already registered") || msg.includes("already exists")) {
    return "An account with this email already exists. Please sign in instead.";
  }
  if (msg.includes("password should be") || msg.includes("least 6 characters")) {
    return "Password must be at least 6 characters.";
  }
  if (msg.includes("fetch") || msg.includes("network")) {
    return "Network error. Please check your internet connection and try again.";
  }
  return err && typeof err === "object" && "message" in err && typeof err.message === "string"
    ? err.message
    : "Could not complete authentication. Please try again.";
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function getInboxProvider(email: string): { name: string; url: string } | null {
  const domain = email.split("@")[1]?.toLowerCase() ?? "";
  if (domain === "gmail.com" || domain === "googlemail.com") {
    return { name: "Gmail", url: "https://mail.google.com/mail/u/0/#inbox" };
  }
  if (domain === "outlook.com" || domain === "hotmail.com" || domain === "live.com") {
    return { name: "Outlook", url: "https://outlook.live.com/mail/0/inbox" };
  }
  if (domain === "yahoo.com") {
    return { name: "Yahoo Mail", url: "https://mail.yahoo.com" };
  }
  return null;
}

function LoginFormInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = sanitizeNextPath(searchParams.get("next"));
  const urlError = searchParams.get("error");
  const isConfirmed = searchParams.get("confirmed") === "true";

  const initialError = React.useMemo(() => {
    if (!urlError) return null;
    if (urlError === "oauth_failed") {
      return "Google sign-in could not be completed. Please try again or sign in with email.";
    }
    if (urlError === "verification_failed") {
      return "The confirmation link was invalid or has already been used. Please sign in below.";
    }
    return "Sign-in could not be completed. Please try again.";
  }, [urlError]);

  const [mode, setMode] = React.useState<"signin" | "signup">("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [resendLoading, setResendLoading] = React.useState(false);
  const [resendCooldown, setResendCooldown] = React.useState(0);
  const [resendSuccess, setResendSuccess] = React.useState(false);
  const [signupSuccessEmail, setSignupSuccessEmail] = React.useState<string | null>(null);
  const [googleLoading, setGoogleLoading] = React.useState(false);
  const [captchaToken, setCaptchaToken] = React.useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = React.useState(0);
  const turnstileEnabled = isTurnstileConfigured();
  const [error, setError] = React.useState<string | null>(initialError);

  const emailInputRef = React.useRef<HTMLInputElement | null>(null);

  // If Supabase redirected here with a hash session (#access_token=...) from an email confirmation,
  // complete the session automatically and redirect to nextPath.
  React.useEffect(() => {
    const supabase = createClient();
    if (!supabase) return;
    if (typeof window !== "undefined" && window.location.hash.includes("access_token=")) {
      setError(null);
      supabase.auth.getSession().then(({ data }) => {
        if (data.session) {
          router.push(nextPath);
          router.refresh();
        }
      });
    }
  }, [nextPath, router]);

  // Countdown timer for resending confirmation email
  React.useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = window.setInterval(() => {
      setResendCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [resendCooldown]);

  function switchMode(nextMode: "signin" | "signup") {
    if (mode === nextMode) return;
    setMode(nextMode);
    setError(null);
    setSignupSuccessEmail(null);
    setResendSuccess(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResendSuccess(false);

    const trimmedEmail = email.trim();
    if (!EMAIL_RE.test(trimmedEmail)) {
      setError("Please enter a valid email address.");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    if (turnstileEnabled && !captchaToken) {
      setError("Please wait for the security check to complete and try again.");
      return;
    }

    const supabase = createClient();
    if (!supabase) {
      setError(
        "Supabase Auth is not configured yet. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      );
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email: trimmedEmail,
          password,
          options: {
            captchaToken: captchaToken ?? undefined,
          },
        });
        setCaptchaReset((n) => n + 1);
        if (signInError) {
          setError(mapAuthError(signInError));
          return;
        }
        router.push(nextPath);
        router.refresh();
      } else {
        const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
        const { data, error: signUpError } = await supabase.auth.signUp({
          email: trimmedEmail,
          password,
          options: {
            emailRedirectTo: redirectTo,
            captchaToken: captchaToken ?? undefined,
          },
        });
        setCaptchaReset((n) => n + 1);
        if (signUpError) {
          setError(mapAuthError(signUpError));
          return;
        }

        if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
          setMode("signin");
          setError("An account with this email already exists. Please sign in with your password.");
          return;
        }

        if (data.session) {
          router.push(nextPath);
          router.refresh();
          return;
        }

        // Switch to sign-in tab with clear, interactive notification banner
        setMode("signin");
        setSignupSuccessEmail(trimmedEmail);
        setResendCooldown(60);
      }
    } catch (err) {
      setError(mapAuthError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleResendConfirmation() {
    const targetEmail = signupSuccessEmail || email.trim();
    if (!targetEmail || resendCooldown > 0 || resendLoading) return;
    setError(null);
    setResendSuccess(false);

    const supabase = createClient();
    if (!supabase) return;

    setResendLoading(true);
    try {
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
      const { error: resendErr } = await supabase.auth.resend({
        type: "signup",
        email: targetEmail,
        options: {
          emailRedirectTo: redirectTo,
        },
      });
      if (resendErr) {
        setError(mapAuthError(resendErr));
        return;
      }
      setResendSuccess(true);
      setResendCooldown(60);
    } catch (err) {
      setError(mapAuthError(err));
    } finally {
      setResendLoading(false);
    }
  }

  async function handleGoogleLogin() {
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError(
        "Supabase Auth is not configured yet. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      );
      return;
    }

    setGoogleLoading(true);
    try {
      const redirectTo = `${window.location.origin}/auth/callback?provider=google&next=${encodeURIComponent(nextPath)}`;
      const { error: oError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo },
      });
      if (oError) {
        setError(mapAuthError(oError));
        setGoogleLoading(false);
      }
    } catch (err) {
      setError(mapAuthError(err));
      setGoogleLoading(false);
    }
  }

  const passwordValid = password.length >= 6;
  const currentEmail = signupSuccessEmail || email.trim();
  const inboxProvider = getInboxProvider(currentEmail);

  return (
    <div className="mx-auto w-full max-w-md px-4 py-12 sm:py-20">
      <Card padding="lg" className="transition-all duration-200">
        <div className="mb-6">
          <p className="font-mono text-xs uppercase tracking-widest text-ink-3">
            Account access
          </p>
          <h1 className="mt-1.5 font-serif text-2xl font-bold text-ink sm:text-3xl">
            {mode === "signin" ? "Sign in to Proofit" : "Create your account"}
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">
            {mode === "signin"
              ? "Welcome back. Enter your email and password to access your saved analyses and rewrites."
              : "Save your resume analyses, track your application history, and unlock AI bullet rewrites."}
          </p>
        </div>

        {/* Segmented Pill Mode Switcher */}
        <div
          role="tablist"
          aria-label="Authentication mode"
          className="relative mb-6 grid grid-cols-2 rounded-pill border border-rule bg-paper-2 p-1 select-none"
        >
          {/* Sliding active pill indicator */}
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute inset-y-1 left-1 w-[calc(50%-0.25rem)] rounded-pill border border-rule/70 bg-surface-raised shadow-xs transition-transform duration-200 ease-out ${
              mode === "signup" ? "translate-x-full" : "translate-x-0"
            }`}
          />
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signin"}
            onClick={() => switchMode("signin")}
            className={`relative z-10 cursor-pointer rounded-pill py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              mode === "signin"
                ? "text-ink font-semibold"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signup"}
            onClick={() => switchMode("signup")}
            className={`relative z-10 cursor-pointer rounded-pill py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              mode === "signup"
                ? "text-ink font-semibold"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            Create account
          </button>
        </div>

        {error ? (
          <div
            role="alert"
            className="mb-5 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger"
          >
            {error}
          </div>
        ) : null}

        {isConfirmed && !error ? (
          <div
            role="status"
            className="mb-5 flex items-center gap-2.5 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm font-medium text-emerald-800"
          >
            <svg className="h-4 w-4 shrink-0 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
            <span>Email confirmed successfully! Please sign in with your password below.</span>
          </div>
        ) : null}

        {/* Appealing & Interactive Verification Notice Banner */}
        {signupSuccessEmail ? (
          <div
            role="status"
            className="mb-5 rounded-2xl border border-accent/25 bg-accent-tint/50 p-4 text-ink shadow-2xs transition-all animate-fade"
          >
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-accent/20 bg-surface-raised text-accent shadow-2xs">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-bold text-ink">
                    Account created! Verification link sent
                  </h3>
                  <button
                    type="button"
                    onClick={() => setSignupSuccessEmail(null)}
                    aria-label="Dismiss notice"
                    className="cursor-pointer rounded-full p-1 text-ink-3 transition-colors hover:bg-paper hover:text-ink"
                  >
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                <p className="mt-1 text-xs leading-relaxed text-ink-2">
                  We sent an activation link to <strong className="font-mono font-semibold text-ink">{signupSuccessEmail}</strong>. Please click the link in your email to activate your account.
                </p>

                {/* Interactive Action Shortcuts */}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {inboxProvider ? (
                    <a
                      href={inboxProvider.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex cursor-pointer items-center gap-1.5 rounded-pill bg-accent px-3 py-1.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-accent-2 active:scale-95"
                    >
                      <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.272H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z" />
                      </svg>
                      <span>Open {inboxProvider.name} ↗</span>
                    </a>
                  ) : null}

                  <button
                    type="button"
                    onClick={handleResendConfirmation}
                    disabled={resendCooldown > 0 || resendLoading}
                    className="inline-flex cursor-pointer items-center gap-1.5 rounded-pill border border-rule bg-surface-raised px-3 py-1.5 text-xs font-medium text-ink shadow-2xs transition-all hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:text-ink-3"
                  >
                    {resendLoading
                      ? "Sending…"
                      : resendCooldown > 0
                        ? `Resend in ${resendCooldown}s`
                        : resendSuccess
                          ? "✓ Link resent!"
                          : "Resend email"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <div className="grid gap-5">
          <form onSubmit={handleSubmit} className="grid gap-4" noValidate>
            <div className="grid gap-1.5">
              <label htmlFor="login-email" className="text-sm font-medium text-ink">
                Email address
              </label>
              <input
                ref={emailInputRef}
                id="login-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setError(null);
                }}
                placeholder="you@example.com"
                className="min-h-11 w-full rounded-control border border-rule bg-paper px-4 text-[15px] text-ink transition-all duration-150 placeholder:text-ink-3 hover:border-rule-2 focus:border-accent focus:bg-surface-raised focus:ring-3 focus:ring-accent/15 focus:outline-none"
              />
            </div>

            <div className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="login-password" className="text-sm font-medium text-ink">
                  Password
                </label>
                {mode === "signup" && password.length > 0 ? (
                  <span
                    className={`font-mono text-[11px] transition-colors ${
                      passwordValid ? "text-accent font-medium" : "text-ink-3"
                    }`}
                  >
                    {passwordValid ? "✓ 6+ characters" : `${password.length}/6 characters`}
                  </span>
                ) : null}
              </div>
              <div className="relative flex items-center">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError(null);
                  }}
                  placeholder={mode === "signin" ? "Enter your password" : "At least 6 characters"}
                  className="min-h-11 w-full rounded-control border border-rule bg-paper pl-4 pr-20 text-[15px] text-ink transition-all duration-150 placeholder:text-ink-3 hover:border-rule-2 focus:border-accent focus:bg-surface-raised focus:ring-3 focus:ring-accent/15 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute right-2 cursor-pointer rounded-pill px-2.5 py-1 font-mono text-[11px] font-semibold tracking-wider text-ink-2 transition-all hover:bg-paper-2 hover:text-ink active:scale-95"
                >
                  {showPassword ? "HIDE" : "SHOW"}
                </button>
              </div>
            </div>

            <TurnstileWidget
              onVerify={setCaptchaToken}
              resetSignal={captchaReset}
            />

            <Button
              type="submit"
              size="md"
              icon="arrow"
              loading={loading}
              className="mt-1 w-full cursor-pointer"
            >
              {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <p className="text-center text-xs text-ink-2">
            {mode === "signin" ? (
              <>
                New to Proofit?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("signup")}
                  className="cursor-pointer font-semibold text-accent underline underline-offset-4 transition-colors hover:text-accent-2"
                >
                  Create an account
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("signin")}
                  className="cursor-pointer font-semibold text-accent underline underline-offset-4 transition-colors hover:text-accent-2"
                >
                  Sign in instead
                </button>
              </>
            )}
          </p>

          <div className="relative flex items-center py-0.5">
            <div className="grow border-t border-rule" />
            <span className="mx-3 shrink font-mono text-xs uppercase text-ink-3">or</span>
            <div className="grow border-t border-rule" />
          </div>

          <Button
            type="button"
            variant="secondary"
            size="md"
            loading={googleLoading}
            onClick={handleGoogleLogin}
            className="w-full cursor-pointer"
          >
            Continue with Google
          </Button>
        </div>

        <p className="mt-6 border-t border-rule pt-4 text-center text-xs text-ink-3">
          Just trying it out?{" "}
          <Link href="/analyze" className="font-medium text-ink underline underline-offset-4 hover:text-accent">
            Run 1 free guest analysis
          </Link>
        </p>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-md px-4 py-24 text-center text-ink-3">Loading…</div>
      }
    >
      <LoginFormInner />
    </Suspense>
  );
}
