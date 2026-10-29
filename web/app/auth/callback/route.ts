import { NextResponse } from "next/server";
import { type EmailOtpType } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";

function sanitizeNextPath(raw: string | null): string {
  if (!raw) return "/analyze";
  const trimmed = raw.trim();
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    return trimmed;
  }
  return "/analyze";
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const provider = searchParams.get("provider");
  const isGoogleOAuth = provider === "google";
  const nextPath = sanitizeNextPath(searchParams.get("next"));

  // 1. PKCE code exchange (Google OAuth or PKCE email links)
  if (code) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        return NextResponse.redirect(`${origin}${nextPath}`);
      }
    }
  }

  // 2. Token hash verification (Supabase email confirmation / recovery)
  if (token_hash && type) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.verifyOtp({ type, token_hash });
      if (!error) {
        return NextResponse.redirect(`${origin}${nextPath}`);
      }
    }
  }

  // 3. Only show Google OAuth error if this callback was explicitly initiated by Google OAuth
  if (isGoogleOAuth) {
    return NextResponse.redirect(
      `${origin}/login?error=oauth_failed&next=${encodeURIComponent(nextPath)}`,
    );
  }

  // 4. For all email confirmation callbacks where session cookie wasn't auto-exchanged
  // (e.g. opened in a different browser/tab or PKCE verifier missing after email verification),
  // redirect to login with the green confirmed banner so the user can sign in with their password.
  return NextResponse.redirect(
    `${origin}/login?confirmed=true&next=${encodeURIComponent(nextPath)}`,
  );
}
