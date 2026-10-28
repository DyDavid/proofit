"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export interface HeaderAuthProps {
  planLabel?: string;
}

export function HeaderAuth({ planLabel = "Free" }: HeaderAuthProps) {
  const router = useRouter();
  const [email, setEmail] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [menuOpen, setMenuOpen] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const supabase = createClient();
    if (!supabase) {
      setReady(true);
      return;
    }

    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
      setReady(true);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setEmail(session?.user?.email ?? null);
      setReady(true);
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  React.useEffect(() => {
    if (!menuOpen) return;
    function handleOutsideClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [menuOpen]);

  async function handleSignOut() {
    setMenuOpen(false);
    const supabase = createClient();
    if (supabase) {
      await supabase.auth.signOut();
    }
    try {
      await fetch("/auth/signout", { method: "POST" });
    } catch {
      // Ignore network error if browser signOut already succeeded
    }
    setEmail(null);
    router.push("/");
    router.refresh();
  }

  if (!ready) {
    return null;
  }

  if (!email) {
    return (
      <Link
        href="/login"
        className="inline-flex min-h-9 items-center rounded-pill border border-rule bg-surface-raised px-4 py-1.5 text-sm font-medium text-ink transition-colors hover:border-ink"
      >
        Sign in
      </Link>
    );
  }

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setMenuOpen((prev) => !prev)}
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        className="inline-flex min-h-9 items-center gap-2 rounded-pill border border-rule bg-surface-raised px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-ink"
      >
        <span className="max-w-[160px] truncate font-medium">{email}</span>
        <span className="rounded-pill bg-accent-tint px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-accent">
          {planLabel}
        </span>
      </button>

      {menuOpen ? (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-48 rounded-control border border-rule bg-surface-raised p-1.5 shadow-lg"
        >
          <Link
            href="/account"
            role="menuitem"
            onClick={() => setMenuOpen(false)}
            className="block rounded-md px-3 py-2 text-sm text-ink transition-colors hover:bg-paper-2"
          >
            Account
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={handleSignOut}
            className="block w-full rounded-md px-3 py-2 text-left text-sm text-danger transition-colors hover:bg-paper-2"
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

