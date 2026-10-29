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
  const nextPath = sanitizeNextPath(searchParams.get("next"));

  // 1. Check for explicit error from provider/Supabase
  const incomingError = searchParams.get("error");
  if (incomingError) {
    const errorCode = searchParams.get("error_code");
    const isOAuth = incomingError.toLowerCase().includes("oauth") || !type;
    return NextResponse.redirect(
      `${origin}/login?error=${isOAuth ? "oauth_failed" : "verification_failed"}&next=${encodeURIComponent(
        nextPath,
      )}${errorCode ? `&reason=${encodeURIComponent(errorCode)}` : ""}`,
    );
  }

  // 2. PKCE code exchange (Google OAuth or PKCE email links)
  if (code) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        return NextResponse.redirect(`${origin}${nextPath}`);
      }
    }
  }

  // 3. Token hash verification (Supabase email confirmation / recovery)
  if (token_hash && type) {
    const supabase = await createClient();
    if (supabase) {
      const { error } = await supabase.auth.verifyOtp({ type, token_hash });
      if (!error) {
        return NextResponse.redirect(`${origin}${nextPath}`);
      }
    }
  }

  // 4. If this was an email confirmation, redirect with confirmed notice rather than failing
  if (type === "signup" || type === "email" || token_hash) {
    return NextResponse.redirect(
      `${origin}/login?confirmed=true&next=${encodeURIComponent(nextPath)}`,
    );
  }

  return NextResponse.redirect(
    `${origin}/login?error=oauth_failed&next=${encodeURIComponent(nextPath)}`,
  );
}
