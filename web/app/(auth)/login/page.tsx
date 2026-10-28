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
    return "Too many attempts, wait a minute before trying again.";
  }
  if (msg.includes("expired")) {
    return "That verification code has expired. Click Resend code to get a new 6-digit code.";
  }
  if (msg.includes("invalid") || msg.includes("token")) {
    return "Invalid verification code. Please check the 6-digit code and try again.";
  }
  if (msg.includes("fetch") || msg.includes("network")) {
    return "Network error. Please check your internet connection and try again.";
  }
  return "Could not complete sign-in. Please try again.";
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function LoginFormInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = sanitizeNextPath(searchParams.get("next"));
  const oauthError = searchParams.get("error");

  const [step, setStep] = React.useState<"email" | "code">("email");
  const [email, setEmail] = React.useState("");
  const [code, setCode] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [googleLoading, setGoogleLoading] = React.useState(false);
  const [cooldown, setCooldown] = React.useState(0);
  const [captchaToken, setCaptchaToken] = React.useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = React.useState(0);
  const turnstileEnabled = isTurnstileConfigured();
  const [error, setError] = React.useState<string | null>(
    oauthError ? "Google sign-in could not be completed. Please try again." : null,
  );
  const [info, setInfo] = React.useState<string | null>(null);

  const codeInputRef = React.useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    if (step === "code") {
      requestAnimationFrame(() => codeInputRef.current?.focus());
    }
  }, [step]);

  React.useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  async function handleSendCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);

    const trimmedEmail = email.trim();
    if (!EMAIL_RE.test(trimmedEmail)) {
      setError("Please enter a valid email address.");
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
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: trimmedEmail,
        options: {
          shouldCreateUser: true,
          captchaToken: captchaToken ?? undefined,
        },
      });
      setCaptchaReset((n) => n + 1);
      if (otpError) {
        setError(mapAuthError(otpError));
        return;
      }
      setEmail(trimmedEmail);
      setCode("");
      setStep("code");
      setCooldown(60);
      setInfo(`We sent a 6-digit verification code to ${trimmedEmail}.`);
    } catch (err) {
      setError(mapAuthError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanCode = code.replace(/\D/g, "");
    if (cleanCode.length !== 6) {
      setError("Please enter the 6-digit verification code from your email.");
      return;
    }

    const supabase = createClient();
    if (!supabase) {
      setError("Supabase Auth is not configured yet.");
      return;
    }

    setLoading(true);
    try {
      const { error: verifyError } = await supabase.auth.verifyOtp({
        email,
        token: cleanCode,
        type: "email",
      });
      if (verifyError) {
        setError(mapAuthError(verifyError));
        return;
      }
      router.push(nextPath);
      router.refresh();
    } catch (err) {
      setError(mapAuthError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleResendCode() {
    if (cooldown > 0 || loading) return;
    setError(null);
    setInfo(null);

    const supabase = createClient();
    if (!supabase) {
      setError("Supabase Auth is not configured yet.");
      return;
    }

    setLoading(true);
    try {
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email,
        options: {
          shouldCreateUser: true,
          captchaToken: captchaToken ?? undefined,
        },
      });
      setCaptchaReset((n) => n + 1);
      if (otpError) {
        setError(mapAuthError(otpError));
        return;
      }
      setCooldown(60);
      setInfo(`Sent a new 6-digit code to ${email}.`);
    } catch (err) {
      setError(mapAuthError(err));
    } finally {
      setLoading(false);
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
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
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

  return (
    <div className="mx-auto w-full max-w-md px-4 py-16 sm:py-24">
      <Card padding="lg">
        <div className="mb-6">
          <p className="font-mono text-xs uppercase tracking-widest text-ink-3">
            Account access
          </p>
          <h1 className="mt-1.5 font-serif text-3xl font-bold text-ink">
            {step === "email" ? "Sign in to Proofit" : "Enter your 6-digit code"}
          </h1>
          <p className="mt-2 text-sm text-ink-2">
            {step === "email"
              ? "Save your resume analyses, track your application history, and unlock AI bullet rewrites."
              : `Enter the 6-digit code sent to ${email}. It expires in 10 minutes.`}
          </p>
        </div>

        {error ? (
          <div
            role="alert"
            className="mb-5 rounded-control border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger"
          >
            {error}
          </div>
        ) : null}

        {info && !error ? (
          <div className="mb-5 rounded-control border border-rule bg-surface-raised px-4 py-3 text-sm text-ink-2">
            {info}
          </div>
        ) : null}

        {step === "email" ? (
          <div className="grid gap-5">
            <form onSubmit={handleSendCode} className="grid gap-4" noValidate>
              <div className="grid gap-1.5">
                <label htmlFor="login-email" className="text-sm font-medium text-ink">
                  Email address
                </label>
                <input
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
                  className="min-h-11 w-full rounded-control border border-rule bg-paper px-3.5 text-[15px] text-ink placeholder:text-ink-3"
                />
              </div>

              <TurnstileWidget
                onVerify={setCaptchaToken}
                resetSignal={captchaReset}
              />

              <Button type="submit" size="md" icon="arrow" loading={loading} className="w-full">
                Send code
              </Button>
            </form>

            <div className="relative flex items-center py-1">
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
              className="w-full"
            >
              Continue with Google
            </Button>
          </div>
        ) : (
          <form onSubmit={handleVerifyCode} className="grid gap-4" noValidate>
            <div className="grid gap-1.5">
              <label htmlFor="login-otp" className="text-sm font-medium text-ink">
                6-digit verification code
              </label>
              <input
                ref={codeInputRef}
                id="login-otp"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => {
                  const digitsOnly = e.target.value.replace(/\D/g, "").slice(0, 6);
                  setCode(digitsOnly);
                  setError(null);
                }}
                onPaste={(e) => {
                  const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
                  if (pasted) {
                    e.preventDefault();
                    setCode(pasted);
                    setError(null);
                  }
                }}
                placeholder="123456"
                className="min-h-12 w-full rounded-control border border-rule bg-paper px-4 text-center font-mono text-2xl tracking-[0.35em] text-ink placeholder:text-ink-3"
              />
            </div>

            <Button
              type="submit"
              size="md"
              icon="arrow"
              loading={loading}
              disabled={code.length !== 6}
              className="w-full"
            >
              Verify
            </Button>

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
              <button
                type="button"
                onClick={handleResendCode}
                disabled={cooldown > 0 || loading}
                className="font-medium text-accent disabled:cursor-not-allowed disabled:text-ink-3"
              >
                {cooldown > 0 ? `Resend code (${cooldown}s)` : "Resend code"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setStep("email");
                  setCode("");
                  setError(null);
                  setInfo(null);
                }}
                className="text-ink-2 underline underline-offset-4 hover:text-ink"
              >
                Change email
              </button>
            </div>
          </form>
        )}

        <p className="mt-6 border-t border-rule pt-4 text-center text-xs text-ink-3">
          Just trying it out?{" "}
          <Link href="/analyze" className="font-medium text-ink underline underline-offset-4">
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

