"use client";

import * as React from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: {
          sitekey: string;
          appearance?: "always" | "execute" | "interaction-only";
          theme?: "light" | "dark" | "auto";
          callback?: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
        },
      ) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId?: string) => void;
    };
  }
}

const TURNSTILE_SCRIPT_ID = "cf-turnstile-script";
const TURNSTILE_SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

export function isTurnstileConfigured(): boolean {
  const key = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  return Boolean(key && key.trim() && !key.includes("REPLACE_ME"));
}

export interface TurnstileWidgetProps {
  onVerify: (token: string | null) => void;
  resetSignal?: number;
}

/**
 * Cloudflare Turnstile managed/invisible widget (Phase 2).
 * Renders nothing when `NEXT_PUBLIC_TURNSTILE_SITE_KEY` is not set.
 */
export function TurnstileWidget({ onVerify, resetSignal = 0 }: TurnstileWidgetProps) {
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY?.trim();
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const widgetIdRef = React.useRef<string | null>(null);
  const onVerifyRef = React.useRef(onVerify);
  onVerifyRef.current = onVerify;

  React.useEffect(() => {
    if (!siteKey || siteKey.includes("REPLACE_ME")) return;

    let cancelled = false;

    function mountWidget() {
      if (cancelled || !containerRef.current || !window.turnstile || !siteKey) return;
      if (widgetIdRef.current) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // Ignore stale widget removal error
        }
        widgetIdRef.current = null;
      }

      widgetIdRef.current = window.turnstile.render(containerRef.current, {
        sitekey: siteKey,
        appearance: "interaction-only",
        theme: "light",
        callback: (token: string) => onVerifyRef.current(token),
        "expired-callback": () => onVerifyRef.current(null),
        "error-callback": () => onVerifyRef.current(null),
      });
    }

    if (window.turnstile) {
      mountWidget();
    } else {
      let script = document.getElementById(TURNSTILE_SCRIPT_ID) as HTMLScriptElement | null;
      if (!script) {
        script = document.createElement("script");
        script.id = TURNSTILE_SCRIPT_ID;
        script.src = TURNSTILE_SCRIPT_SRC;
        script.async = true;
        script.defer = true;
        document.head.appendChild(script);
      }
      script.addEventListener("load", mountWidget);
      return () => {
        cancelled = true;
        script?.removeEventListener("load", mountWidget);
        if (widgetIdRef.current && window.turnstile) {
          try {
            window.turnstile.remove(widgetIdRef.current);
          } catch {
            // Ignore cleanup error
          }
          widgetIdRef.current = null;
        }
      };
    }

    return () => {
      cancelled = true;
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // Ignore cleanup error
        }
        widgetIdRef.current = null;
      }
    };
  }, [siteKey]);

  React.useEffect(() => {
    if (resetSignal === 0) return;
    onVerifyRef.current(null);
    if (widgetIdRef.current && window.turnstile) {
      try {
        window.turnstile.reset(widgetIdRef.current);
      } catch {
        // Ignore reset error
      }
    }
  }, [resetSignal]);

  if (!siteKey || siteKey.includes("REPLACE_ME")) {
    return null;
  }

  return <div ref={containerRef} className="min-h-1" />;
}

