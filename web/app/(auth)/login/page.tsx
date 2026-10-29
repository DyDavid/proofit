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
    return "Email not confirmed yet. Check your inbox or disable 'Confirm email' in your Supabase Auth settings.";
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

function LoginFormInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = sanitizeNextPath(searchParams.get("next"));
  const oauthError = searchParams.get("error");

  const [mode, setMode] = React.useState<"signin" | "signup">("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [googleLoading, setGoogleLoading] = React.useState(false);
  const [captchaToken, setCaptchaToken] = React.useState<string | null>(null);
  const [captchaReset, setCaptchaReset] = React.useState(0);
  const turnstileEnabled = isTurnstileConfigured();
  const [error, setError] = React.useState<string | null>(
    oauthError ? "Google sign-in could not be completed. Please try again." : null,
  );
  const [info, setInfo] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);

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

        setMode("signin");
        setInfo(
          "Account created! If email confirmation is enabled on your Supabase project, check your inbox or disable 'Confirm email' in Supabase Auth settings to sign in immediately.",
        );
      }
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
            {mode === "signin" ? "Sign in to Proofit" : "Create your account"}
          </h1>
          <p className="mt-2 text-sm text-ink-2">
            Save your resume analyses, track your application history, and unlock AI bullet rewrites.
          </p>
        </div>

        {/* Mode Switcher Tabs */}
        <div className="mb-6 grid grid-cols-2 rounded-control border border-rule bg-paper-2 p-1">
          <button
            type="button"
            onClick={() => {
              setMode("signin");
              setError(null);
              setInfo(null);
            }}
            className={`rounded-[6px] py-2 text-sm font-medium transition-all ${
              mode === "signin"
                ? "bg-surface-raised text-ink shadow-xs"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => {
              setMode("signup");
              setError(null);
              setInfo(null);
            }}
            className={`rounded-[6px] py-2 text-sm font-medium transition-all ${
              mode === "signup"
                ? "bg-surface-raised text-ink shadow-xs"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            Create account
          </button>
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

        <div className="grid gap-5">
          <form onSubmit={handleSubmit} className="grid gap-4" noValidate>
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

            <div className="grid gap-1.5">
              <label htmlFor="login-password" className="text-sm font-medium text-ink">
                Password
              </label>
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
                  className="min-h-11 w-full rounded-control border border-rule bg-paper pl-3.5 pr-16 text-[15px] text-ink placeholder:text-ink-3"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="absolute right-3 font-mono text-xs font-medium text-ink-3 hover:text-ink"
                >
                  {showPassword ? "HIDE" : "SHOW"}
                </button>
              </div>
            </div>

            <TurnstileWidget
              onVerify={setCaptchaToken}
              resetSignal={captchaReset}
            />

            <Button type="submit" size="md" icon="arrow" loading={loading} className="w-full">
              {mode === "signin" ? "Sign in" : "Create account"}
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
