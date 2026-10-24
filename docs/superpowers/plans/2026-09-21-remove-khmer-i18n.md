# Remove Khmer / next-intl Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Proofit's `web/` app English-only. Remove `next-intl` entirely (package, middleware, `[locale]` routing), delete `km.json` and every Khmer-only piece of content (LocaleSwitcher, CI parity check, Khmer font subset, Khmer copy in `BRAND.md` and `engine/rewrite/forbidden.json`), while preserving 100% of the existing English copy and every screen's current behavior.

**Architecture:** Replace next-intl's runtime (`useTranslations`/`getTranslations`/`t.rich`, locale-aware `Link`/`useRouter`/`redirect`) with a small local module, `web/lib/copy.tsx`, that reads `web/messages/en.json` directly and exposes the *same call signatures* next-intl did. This means the ~35 existing `t("key", {vars})` / `t.rich("key", {tags})` call sites across 19 files need only an **import swap**, not a rewrite — the biggest source of risk (typos in re-transcribed copy) is eliminated by keeping `en.json` as the single source of truth. Routes move from `app/[locale]/*` to `app/*`; the two-layout split (`app/layout.tsx` pass-through + `app/[locale]/layout.tsx` real layout) collapses into one `app/layout.tsx`.

**Tech Stack:** Next.js 15 (App Router), TypeScript strict, Tailwind v4, React 19. No test runner exists in `web/` today — verification is `npx tsc --noEmit`, `npm run build`, and `npm run lint`, the same gates `web`'s CI job already uses.

**Spec:** `PERSON_B_PLAN_v2.md` (original plan — still documents Khmer as a "Locked Decision"; this plan is a deliberate, user-directed deviation from that section, confirmed via AskUserQuestion in-session, and does not edit `PERSON_B_PLAN_v2.md` itself — see "Out of scope" below).

## Global Constraints

- Every existing `t("key", vars)` and `t.rich("key", tags)` call site keeps its exact key strings and variable names — only the *import* changes, never the call body, unless a step below says otherwise.
- `web/messages/en.json` content is preserved verbatim (not touched by this plan) — it becomes the sole copy source.
- No new npm dependency is added. No new test framework is introduced.
- `@/*` resolves to `web/*` (see `web/tsconfig.json`), so `@/lib/copy` means `web/lib/copy.tsx`.
- Run all commands from the repo root unless a step says `cd web`.
- Commit after every task (use `git add <files>` with explicit paths, never `-A`).

---

### Task 1: Build the `next-intl` replacement (`web/lib/copy.tsx`)

**Files:**
- Create: `web/lib/copy.tsx`

**Interfaces:**
- Produces: `useTranslations(namespace?: string): Translator`, `getTranslations(namespaceOrOptions?: string | { namespace?: string }): Promise<Translator>`, and the `Translator` type — a callable `(key: string, vars?: Record<string, string | number>) => string` that also carries `.rich(key: string, tags: Record<string, (chunks: ReactNode) => ReactNode>) => ReactNode`. Every later task imports these two functions from `@/lib/copy` in place of `next-intl` / `next-intl/server`.

- [ ] **Step 1: Write `web/lib/copy.tsx`**

```tsx
import { Fragment, type ReactNode } from "react";
import en from "../messages/en.json";

/**
 * Proofit's replacement for next-intl (removed — English only now, no more
 * `km` locale). Same call shape as `useTranslations`/`getTranslations` so
 * every existing `t("key")` / `t.rich("key", {...})` call site needed only
 * an import swap, not a rewrite.
 */

type MessageNode = string | { [key: string]: MessageNode };

const messages: MessageNode = en;

function resolve(path: string): MessageNode | undefined {
  return path.split(".").reduce<MessageNode | undefined>((node, key) => {
    if (typeof node === "object" && node !== null && key in node) {
      return node[key];
    }
    return undefined;
  }, messages);
}

function interpolate(
  template: string,
  vars?: Record<string, string | number>,
): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/** One level of `<tag>chunk</tag>` substitution — the only rich-text shape
 * Proofit's copy actually uses (landing page's `hero.title`). */
function renderRich(
  template: string,
  tags: Record<string, (chunks: ReactNode) => ReactNode>,
): ReactNode {
  const tagPattern = /<(\w+)>(.*?)<\/\1>/g;
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = tagPattern.exec(template)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(template.slice(lastIndex, match.index));
    }
    const [full, tagName, inner] = match;
    const render = tags[tagName];
    nodes.push(
      <Fragment key={key++}>{render ? render(inner) : inner}</Fragment>,
    );
    lastIndex = match.index + full.length;
  }
  if (lastIndex < template.length) {
    nodes.push(template.slice(lastIndex));
  }
  return nodes;
}

function requireString(fullKey: string): string {
  const value = resolve(fullKey);
  if (typeof value !== "string") {
    throw new Error(`Missing copy for "${fullKey}"`);
  }
  return value;
}

export interface Translator {
  (key: string, vars?: Record<string, string | number>): string;
  rich: (
    key: string,
    tags: Record<string, (chunks: ReactNode) => ReactNode>,
  ) => ReactNode;
}

function makeTranslator(namespace?: string): Translator {
  const withNamespace = (key: string) =>
    namespace ? `${namespace}.${key}` : key;

  const t = ((key: string, vars?: Record<string, string | number>) =>
    interpolate(requireString(withNamespace(key)), vars)) as Translator;

  t.rich = (key, tags) => renderRich(requireString(withNamespace(key)), tags);

  return t;
}

/** Drop-in replacement for next-intl's `useTranslations` — not an actual
 * React hook (no internal state), so it is safe to call from server
 * components too. */
export function useTranslations(namespace?: string): Translator {
  return makeTranslator(namespace);
}

/** Drop-in replacement for next-intl/server's `getTranslations`. Stays
 * async to match every existing `await getTranslations(...)` call site. */
export async function getTranslations(
  namespaceOrOptions?: string | { namespace?: string },
): Promise<Translator> {
  const namespace =
    typeof namespaceOrOptions === "string"
      ? namespaceOrOptions
      : namespaceOrOptions?.namespace;
  return makeTranslator(namespace);
}
```

- [ ] **Step 2: Type-check the new file in isolation**

Run: `cd web && npx tsc --noEmit`
Expected: no errors referencing `lib/copy.tsx` (errors in other files that still import `next-intl` are expected at this point — every other task hasn't run yet — ignore those for now and only confirm `lib/copy.tsx` itself is clean, e.g. `npx tsc --noEmit 2>&1 | grep "lib/copy"` prints nothing).

- [ ] **Step 3: Commit**

```bash
git add web/lib/copy.tsx
git commit -m "feat(web): add next-intl-free translator backed by en.json"
```

---

### Task 2: Flatten routing — merge layouts, move pages out of `[locale]`

**Files:**
- Create: `web/app/layout.tsx` (replaces the current pass-through version)
- Create: `web/app/about/page.tsx`, `web/app/analyze/page.tsx`, `web/app/page.tsx`, `web/app/progress/page.tsx`, `web/app/results/page.tsx`
- Delete: `web/app/[locale]/layout.tsx`, `web/app/[locale]/about/page.tsx`, `web/app/[locale]/analyze/page.tsx`, `web/app/[locale]/page.tsx`, `web/app/[locale]/progress/page.tsx`, `web/app/[locale]/results/page.tsx`, and the now-empty `web/app/[locale]/` directory

**Interfaces:**
- Consumes: `useTranslations`, `getTranslations` from `@/lib/copy` (Task 1).

- [ ] **Step 1: Move the 5 page files with git, preserving history**

```bash
mkdir -p web/app/about web/app/analyze web/app/progress web/app/results
git mv "web/app/[locale]/about/page.tsx" web/app/about/page.tsx
git mv "web/app/[locale]/analyze/page.tsx" web/app/analyze/page.tsx
git mv "web/app/[locale]/page.tsx" web/app/page.tsx
git mv "web/app/[locale]/progress/page.tsx" web/app/progress/page.tsx
git mv "web/app/[locale]/results/page.tsx" web/app/results/page.tsx
```

- [ ] **Step 2: Fix `web/app/about/page.tsx`'s import**

Change line 1 from:
```tsx
import { getTranslations } from "next-intl/server";
```
to:
```tsx
import { getTranslations } from "@/lib/copy";
```
Nothing else in this file changes.

- [ ] **Step 3: Fix `web/app/analyze/page.tsx`'s import**

Same one-line change as Step 2 (line 1, identical old/new text). Nothing else changes.

- [ ] **Step 4: Fix `web/app/page.tsx`'s import**

Same one-line change as Step 2 (line 1, identical old/new text). The `t.rich("hero.title", { em: (chunks) => <em className="italic text-lac">{chunks}</em> })` call later in the file is unchanged — `Translator.rich` from Task 1 has the same signature.

- [ ] **Step 5: Fix `web/app/progress/page.tsx`'s imports and the redirect call**

Change line 1 from:
```tsx
import { getLocale, getTranslations } from "next-intl/server";
```
to:
```tsx
import { getTranslations } from "@/lib/copy";
```

Change line 6 from:
```tsx
import { redirect } from "@/i18n/routing";
```
to:
```tsx
import { redirect } from "next/navigation";
```

Change the body of the `if (!id)` block from:
```tsx
  if (!id) {
    redirect({ href: "/analyze", locale: await getLocale() });
  }
```
to:
```tsx
  if (!id) {
    redirect("/analyze");
  }
```
Nothing else in this file changes.

- [ ] **Step 6: `web/app/results/page.tsx` needs no edits**

It has no `next-intl` import — confirm with `grep -n "next-intl\|i18n/routing" web/app/results/page.tsx` (expect no output).

- [ ] **Step 7: Replace `web/app/layout.tsx` with the merged layout**

Overwrite `web/app/layout.tsx` (the current pass-through file) with:

```tsx
import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Kantumruy_Pro } from "next/font/google";
import type { ReactNode } from "react";
import Footer from "@/components/layout/Footer";
import Header from "@/components/layout/Header";
import { getTranslations } from "@/lib/copy";
import "./globals.css";

/** Kantumruy Pro is the single UI font (BRAND.md §4). */
const kantumruyPro = Kantumruy_Pro({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-kantumruy",
  display: "swap",
});

/** Display face for headlines and the big coverage numbers (BRAND.md §4). */
const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

/** Label/data face: eyebrows, timestamps, verdict pills, stamps, confidence
 * figures (BRAND.md §4). */
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  const tLanding = await getTranslations("landing");

  const appName = t("appName");

  return {
    title: {
      default: `${appName} · ${t("tagline")}`,
      template: `%s · ${appName}`,
    },
    description: tLanding("hero.subtitle"),
    applicationName: appName,
  };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${kantumruyPro.variable} ${fraunces.variable} ${ibmPlexMono.variable}`}
      data-scroll-behavior="smooth"
    >
      <body
        className={`${kantumruyPro.className} flex min-h-screen flex-col bg-paper leading-[1.75] text-ink antialiased`}
      >
        <Header />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
```

- [ ] **Step 8: Delete the old locale layout and the empty directory**

```bash
git rm "web/app/[locale]/layout.tsx"
rmdir "web/app/[locale]" 2>/dev/null || true
```

- [ ] **Step 9: Verify the route tree**

Run: `find web/app -name "page.tsx" -o -name "layout.tsx" | sort`
Expected: exactly `web/app/about/page.tsx`, `web/app/analyze/page.tsx`, `web/app/layout.tsx`, `web/app/page.tsx`, `web/app/progress/page.tsx`, `web/app/results/page.tsx` — no `[locale]` anywhere.

- [ ] **Step 10: Commit**

```bash
git add web/app
git commit -m "refactor(web): flatten [locale] routing to a single English route tree"
```

---

### Task 3: Migrate every component's `next-intl` / `@/i18n/routing` import

**Files:**
- Modify: `web/components/analyze/AnalysisHistory.tsx`, `web/components/analyze/JobPostPanel.tsx`, `web/components/analyze/AnalyzeForm.tsx`, `web/components/analyze/ResumeDropzone.tsx`, `web/components/progress/ProgressStepper.tsx`, `web/components/results/CountryFormat.tsx`, `web/components/results/BaselineToggle.tsx`, `web/components/results/ResultsById.tsx`, `web/components/results/HiddenStrengths.tsx`, `web/components/results/ResultsView.tsx`, `web/components/results/ResultsInteractive.tsx`, `web/components/ui/Button.tsx`, `web/components/layout/Footer.tsx`

**Interfaces:**
- Consumes: `useTranslations` from `@/lib/copy` (Task 1). None of these files call `getTranslations` (server-only) — only the 5 page files in Task 2 do.

This task is 13 mechanical import swaps. In every file below, only the listed line(s) change — nothing else in the file (including every `t(...)`/`useTranslations(...)` call body) changes.

- [ ] **Step 1: `web/components/analyze/AnalysisHistory.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.
Line 9, from `import { Link } from "@/i18n/routing";` to `import Link from "next/link";`.

- [ ] **Step 2: `web/components/analyze/JobPostPanel.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 3: `web/components/analyze/AnalyzeForm.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.
Line 10, from `import { useRouter } from "@/i18n/routing";` to `import { useRouter } from "next/navigation";`.

- [ ] **Step 4: `web/components/analyze/ResumeDropzone.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 5: `web/components/progress/ProgressStepper.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.
Line 7, from `import { useRouter } from "@/i18n/routing";` to `import { useRouter } from "next/navigation";`.

- [ ] **Step 6: `web/components/results/CountryFormat.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 7: `web/components/results/BaselineToggle.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 8: `web/components/results/ResultsById.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.
Line 8, from `import { useRouter } from "@/i18n/routing";` to `import { useRouter } from "next/navigation";`.

Also fix the stale comment around line 17-20, from:
```tsx
/**
 * Error codes a `status: "failed"` analysis can carry (docs/errors.md §2).
 * An unrecognised code falls back to `errors.INTERNAL` rather than being
 * handed to next-intl unchecked — same allowlist-then-fallback rule as
 * `ProgressStepper`, which polls the same field.
 */
```
to:
```tsx
/**
 * Error codes a `status: "failed"` analysis can carry (docs/errors.md §2).
 * An unrecognised code falls back to `errors.INTERNAL` rather than being
 * looked up unchecked — same allowlist-then-fallback rule as
 * `ProgressStepper`, which polls the same field.
 */
```

- [ ] **Step 9: `web/components/results/HiddenStrengths.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 10: `web/components/results/ResultsView.tsx`**

Line 1, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

Also fix the stale doc comment, from:
```tsx
/**
 * The full Results screen body, as a pure function of one `Match` — shared by
 * the static "try a sample" path (`app/[locale]/results/page.tsx`, no `?id=`)
 * and the real-analysis path (`ResultsById.tsx`, fetched by `?id=`). Uses
 * `next-intl`'s isomorphic `useTranslations` (not the `/server` variant) so
 * the exact same component works from a Server or a Client Component.
 */
```
to:
```tsx
/**
 * The full Results screen body, as a pure function of one `Match` — shared by
 * the static "try a sample" path (`app/results/page.tsx`, no `?id=`) and the
 * real-analysis path (`ResultsById.tsx`, fetched by `?id=`). `useTranslations`
 * from `@/lib/copy` works identically from a Server or a Client Component.
 */
```

- [ ] **Step 11: `web/components/results/ResultsInteractive.tsx`**

Line 3, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.

- [ ] **Step 12: `web/components/ui/Button.tsx`**

Line 3, from `import { Link } from "@/i18n/routing";` to `import Link from "next/link";`.

Also fix the stale comment near the bottom, from:
```tsx
/**
 * The one button in the app. Carries no text of its own — every label is a
 * child supplied by the caller through next-intl `t()`.
 */
```
to:
```tsx
/**
 * The one button in the app. Carries no text of its own — every label is a
 * child supplied by the caller through `t()`.
 */
```

- [ ] **Step 13: `web/components/layout/Footer.tsx`**

Line 1, from `import { useTranslations } from "next-intl";` to `import { useTranslations } from "@/lib/copy";`.
Line 2, from `import { Link } from "@/i18n/routing";` to `import Link from "next/link";`.

- [ ] **Step 14: Verify no stray imports remain in this file set**

Run: `grep -rln "next-intl\|@/i18n/routing" web/components`
Expected: only `web/components/layout/Header.tsx` and `web/components/layout/LocaleSwitcher.tsx` print — both handled in Task 4.

- [ ] **Step 15: Type-check**

Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "app/layout.tsx\|Header.tsx\|LocaleSwitcher"`
Expected: no output (any remaining errors should only be in the two files Task 4 hasn't touched yet).

- [ ] **Step 16: Commit**

```bash
git add web/components/analyze web/components/progress web/components/results web/components/ui/Button.tsx web/components/layout/Footer.tsx
git commit -m "refactor(web): migrate component copy/nav imports off next-intl"
```

---

### Task 4: Remove the locale switcher, next-intl package, and Khmer message file

**Files:**
- Delete: `web/components/layout/LocaleSwitcher.tsx`, `web/middleware.ts`, `web/i18n/routing.ts`, `web/i18n/request.ts`, `web/messages/km.json`
- Modify: `web/components/layout/Header.tsx`, `web/next.config.ts`, `web/package.json`

**Interfaces:**
- Consumes: `useTranslations` from `@/lib/copy` (Task 1).

- [ ] **Step 1: Delete the locale switcher and its infra**

```bash
git rm web/components/layout/LocaleSwitcher.tsx
git rm web/middleware.ts
git rm web/i18n/routing.ts web/i18n/request.ts
rmdir web/i18n 2>/dev/null || true
git rm web/messages/km.json
```

- [ ] **Step 2: Update `web/components/layout/Header.tsx`**

Replace the whole file with:

```tsx
import { useTranslations } from "@/lib/copy";
import { Button } from "@/components/ui/Button";
import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", key: "nav.home" },
  { href: "/analyze", key: "nav.analyze" },
  { href: "/about", key: "nav.about" },
] as const;

/**
 * Site header: Proofit wordmark, the three primary routes, and a primary
 * CTA. Server component.
 */
export default function Header() {
  const t = useTranslations("common");

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper-3/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-7 gap-y-3 px-4 py-3.5 sm:px-6">
        <Link href="/" className="shrink-0 font-serif text-2xl italic text-ink">
          {t("appName")}
        </Link>

        <nav className="order-3 flex w-full flex-wrap items-center gap-x-6 gap-y-2 sm:order-none sm:w-auto">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="border-b-2 border-transparent py-1 font-medium text-ink-2 transition-colors hover:border-rule hover:text-ink"
            >
              {t(item.key)}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-4">
          <Button as="a" href="/analyze" size="sm" className="hidden sm:inline-flex">
            {t("action.analyze")}
          </Button>
        </div>
      </div>
    </header>
  );
}
```

(Only change from the original: the `LocaleSwitcher` import and its `<LocaleSwitcher />` usage are removed, `useTranslations` comes from `@/lib/copy`, `Link` comes from `next/link`.)

- [ ] **Step 3: Drop the next-intl plugin wrapper from `web/next.config.ts`**

Replace the file with:

```tsx
import type { NextConfig } from "next";

/**
 * PERSON_B_PLAN_v2.md §8.3: the browser only ever talks to its own origin.
 * `/api/*` is rewritten to the FastAPI service, so there is no CORS
 * configuration and no second origin in the client code.
 *
 * Locally this defaults to the uvicorn dev server; on Vercel it is set to the
 * Render service URL via the NEXT_PUBLIC_API_URL environment variable.
 */
const apiBaseUrl = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Emits .next/standalone: a self-contained server.js plus only the
  // node_modules actually reachable at runtime. Required by web/Dockerfile's
  // runner stage, which powers `docker compose up` and the offline laptop
  // fallback at the defense (PERSON_B_PLAN_v2.md §5 Phase 7 task 2b).
  // Vercel ignores this and uses its own build output, so it is safe in both.
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBaseUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 4: Uninstall the `next-intl` package**

```bash
cd web && npm uninstall next-intl && cd ..
```
This removes the `"next-intl": "^4.14.3"` line from `web/package.json`'s `dependencies` and updates `web/package-lock.json` automatically.

- [ ] **Step 5: Confirm no code still imports it**

Run: `grep -rln "next-intl" web --include="*.ts" --include="*.tsx"`
Expected: no output.

- [ ] **Step 6: Type-check and build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: both succeed with no errors.

- [ ] **Step 7: Commit**

```bash
git add web/components/layout/Header.tsx web/next.config.ts web/package.json web/package-lock.json
git rm -r --cached web/messages/km.json 2>/dev/null || true
git commit -m "refactor(web): remove next-intl, LocaleSwitcher, middleware, and km.json"
```

---

### Task 5: Clean up `web/app/globals.css`

**Files:**
- Modify: `web/app/globals.css`

- [ ] **Step 1: Simplify the file header comment**

Change:
```css
/* ==========================================================================
   Proofit — design system
   "Prove your fit" / បញ្ជាក់ភាពសក្តិសមរបស់អ្នក

   Warm paper-and-ink editorial system (BRAND.md §3/§4, revised 12 Sep 2026).
   Tailwind v4: there is NO tailwind.config.ts. Every design token lives here,
   once, inside @theme.

   This system has no dark mode. The reference it matches (a working
   prototype predating this file) has none either — a paper background does
   not have a natural dark inverse, and inventing one un-reviewed would be
   guessing at a look nobody has approved. If dark mode is wanted later it
   gets its own design pass, not a mechanical colour inversion here.

   Accessibility (PERSON_B_PLAN_v2.md Phase 0.5): a verdict is NEVER colour
   alone. Components pair every verdict tone with an inline SVG icon and the
   word itself — see components/ui/VerdictIcon.tsx.

   Khmer (PERSON_B_PLAN_v2.md §7.4): body line-height >= 1.7, never text-xs.
   Khmer script stacks subscript consonants below the baseline and clips at
   normal line heights. Fraunces and IBM Plex Mono have no Khmer glyphs, so
   `font-serif` / `font-mono` fall back to Kantumruy Pro under
   `html[lang="km"]` — see the base layer below.
   ========================================================================== */
```
to:
```css
/* ==========================================================================
   Proofit — design system
   "Prove your fit"

   Warm paper-and-ink editorial system (BRAND.md §3/§4, revised 12 Sep 2026).
   Tailwind v4: there is NO tailwind.config.ts. Every design token lives here,
   once, inside @theme.

   This system has no dark mode. The reference it matches (a working
   prototype predating this file) has none either — a paper background does
   not have a natural dark inverse, and inventing one un-reviewed would be
   guessing at a look nobody has approved. If dark mode is wanted later it
   gets its own design pass, not a mechanical colour inversion here.

   Accessibility (PERSON_B_PLAN_v2.md Phase 0.5): a verdict is NEVER colour
   alone. Components pair every verdict tone with an inline SVG icon and the
   word itself — see components/ui/VerdictIcon.tsx.
   ========================================================================== */
```

- [ ] **Step 2: Drop the Khmer font fallback and rename the leading token**

Change:
```css
  /* ---- Type: display / body / data, one role each (BRAND.md §4). ------- */
  --font-serif:
    var(--font-fraunces), "Iowan Old Style", "Palatino Linotype", Georgia,
    serif;
  --font-sans:
    var(--font-kantumruy), "Kantumruy Pro", ui-sans-serif, system-ui,
    -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
    "Noto Sans Khmer", sans-serif;
  --font-mono:
    var(--font-plex-mono), "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas,
    monospace;

  /* Khmer body copy. Exposed as the `leading-khmer` utility. */
  --leading-khmer: 1.75;
```
to:
```css
  /* ---- Type: display / body / data, one role each (BRAND.md §4). ------- */
  --font-serif:
    var(--font-fraunces), "Iowan Old Style", "Palatino Linotype", Georgia,
    serif;
  --font-sans:
    var(--font-kantumruy), "Kantumruy Pro", ui-sans-serif, system-ui,
    -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono:
    var(--font-plex-mono), "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas,
    monospace;

  /* Relaxed body-copy leading (BRAND.md §4). */
  --leading-body: 1.75;
```

- [ ] **Step 3: Update the `body` rule's line-height comment and variable**

Change:
```css
    font-family: var(--font-sans);
    /* Khmer rule: body copy never drops below 1.7. */
    line-height: var(--leading-khmer);
```
to:
```css
    font-family: var(--font-sans);
    /* Relaxed body leading — BRAND.md §4. */
    line-height: var(--leading-body);
```

- [ ] **Step 4: Drop the Khmer-subscript heading comment**

Change:
```css
  /* Headings may tighten, but not below the point where Khmer subscripts
     collide with the line above. */
  h1,
```
to:
```css
  h1,
```

- [ ] **Step 5: Delete the `html[lang="km"]` font-fallback rule entirely**

Remove this whole block (it sits between the heading rules and `:focus-visible`):
```css
  /* Fraunces and IBM Plex Mono have no Khmer glyphs (BRAND.md §4): fall back
     to Kantumruy Pro SemiBold under the Khmer locale, centrally, so no
     component ever needs a Khmer-specific class of its own. */
  html[lang="km"] .font-serif,
  html[lang="km"] .font-mono {
    font-family: var(--font-sans);
    font-weight: 600;
    letter-spacing: 0;
  }

```
so that the heading rule's closing brace is followed directly by the `:focus-visible` rule.

- [ ] **Step 6: Delete the unused `.khmer-body` utility**

Change:
```css
@layer components {
  /* Apply to any block of Khmer body copy that is not the <body> default,
     e.g. inside a component that tightens leading for Latin. */
  .khmer-body {
    line-height: var(--leading-khmer);
  }

  /* Visually hidden but announced by screen readers. */
```
to:
```css
@layer components {
  /* Visually hidden but announced by screen readers. */
```

- [ ] **Step 7: Confirm no Khmer references remain**

Run: `grep -in "khmer\|lang=\"km\"" web/app/globals.css`
Expected: no output.

- [ ] **Step 8: Build**

Run: `cd web && npm run build`
Expected: succeeds (Tailwind v4 re-resolves `@theme` tokens at build time — a stale `--leading-khmer` reference anywhere would fail the build with an unresolved CSS variable, so a clean build is a real check here, not just a smoke test).

- [ ] **Step 9: Commit**

```bash
git add web/app/globals.css
git commit -m "style(web): drop Khmer-specific CSS, rename --leading-khmer to --leading-body"
```

---

### Task 6: Remove the i18n CI job and the parity-check script

**Files:**
- Delete: `scripts/i18n-check.mjs`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Delete the script**

```bash
git rm scripts/i18n-check.mjs
```

- [ ] **Step 2: Remove the i18n job step from `.github/workflows/ci.yml`**

Change:
```yaml
      - name: i18n key parity (en.json ⇄ km.json)
        # PERSON_B_PLAN_v2.md §7.1 and §5 Phase 1 task 6. Exits non-zero if a key
        # exists in one locale file and not the other. A missing Khmer key does
        # not crash the app — next-intl falls back — so it ships silently and is
        # discovered by a Khmer-first user, which is exactly the failure the
        # Week 12 QA session is too late to catch cheaply. This is that guard.
        # Run from the repository root: the script lives in scripts/, not web/.
        run: node scripts/i18n-check.mjs
```
Delete this step entirely (it's the last step in the `web` job — remove it and the blank line before it, leaving `npm run build` as the job's final step).

- [ ] **Step 3: Update the job name and the header comment**

Change:
```yaml
  web:
    name: web — typecheck, build, i18n parity
```
to:
```yaml
  web:
    name: web — typecheck, build
```

Change the header comment block near the top of the file:
```yaml
#   web ..... tsc + next build + i18n .. the app compiles and km.json has not
#                                        drifted from en.json
```
to:
```yaml
#   web ..... tsc + next build ......... the app compiles
```

- [ ] **Step 4: Verify no other reference to the script or km.json remains in CI**

Run: `grep -n "i18n\|km.json" .github/workflows/ci.yml`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git rm scripts/i18n-check.mjs 2>/dev/null || true
git commit -m "ci: drop the i18n key-parity job now that km.json is gone"
```

---

### Task 7: Collapse `forbidden.json`'s bilingual `reason` fields

**Files:**
- Modify: `engine/rewrite/forbidden.json`, `engine/rewrite/validate.py`

**Interfaces:**
- Produces: `ForbiddenPhrase.reason: str` (was `reason_en` + `reason_km`). `Violation.reason` (in `engine/rewrite/models.py`) is unaffected — it already just takes a `str`.

- [ ] **Step 1: Simplify `engine/rewrite/forbidden.json`**

Replace the file with:

```json
{
  "version": "1.0.0",
  "applies_to_evidence_types": ["coursework", "project", "competition", "volunteer"],
  "forbidden_phrases": [
    {
      "phrase": "professional",
      "reason": "Describes unpaid coursework or a personal project as professional work."
    },
    {
      "phrase": "employed",
      "reason": "Claims an employment relationship the cited evidence does not record."
    },
    {
      "phrase": "worked at",
      "reason": "Names an employer for evidence that is not employment."
    },
    {
      "phrase": "years of experience",
      "reason": "Converts project or coursework duration into professional experience."
    },
    {
      "phrase": "engineer at",
      "reason": "Assigns a job title at an organisation on non-employment evidence."
    }
  ]
}
```

- [ ] **Step 2: Update `engine/rewrite/validate.py`'s `ForbiddenPhrase` model**

Change:
```python
class ForbiddenPhrase(_ForbiddenBase):
    phrase: str = Field(..., min_length=1)
    reason_en: str = Field(..., min_length=1)
    reason_km: str = Field(..., min_length=1)
```
to:
```python
class ForbiddenPhrase(_ForbiddenBase):
    phrase: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
```

- [ ] **Step 3: Update the `Violation` construction**

Change:
```python
        Violation(claim=entry.phrase, reason=entry.reason_en)
```
to:
```python
        Violation(claim=entry.phrase, reason=entry.reason)
```

- [ ] **Step 4: Run the engine test suite**

Run: `cd /Users/macbook/AUPP_FALL_2026/FYP && .venv/bin/pytest tests/test_rewrite_validator.py tests/test_country_rules.py -v`
Expected: all tests pass (per the earlier audit, no test asserts on `.reason_en`/`.reason_km` by name, so this is a pure rename with no expected behavior change — the assertion above confirms it).

- [ ] **Step 5: Commit**

```bash
git add engine/rewrite/forbidden.json engine/rewrite/validate.py
git commit -m "refactor(engine): collapse forbidden.json's reason_en/reason_km into reason"
```

---

### Task 8: Clean up `BRAND.md` and do the final full-repo verification

**Files:**
- Modify: `BRAND.md`

- [ ] **Step 1: Simplify the file header**

Change:
```markdown
> Phase 0, task 1 (`PERSON_B_PLAN_v2.md` §5). This file is the single source of
> truth for the product name, the colour tokens, and the Khmer verdict vocabulary.
> Plan §7.3 requires the Khmer verdict words below to be used **identically** in the
> UI, in any export, and on the defense slides. Change them here first, everywhere else second.
```
to:
```markdown
> Phase 0, task 1 (`PERSON_B_PLAN_v2.md` §5). This file is the single source of
> truth for the product name and the colour tokens.
```

- [ ] **Step 2: Drop the Khmer tagline row**

Change:
```markdown
### Tagline

| Locale | Tagline |
|---|---|
| English (`en`) | **Prove your fit** |
| Khmer (`km`) | **បញ្ជាក់ភាពសក្តិសមរបស់អ្នក** |

The English tagline is three words and stays three words. Do not extend it to
"Prove your fit, faster" or any variant — the whole point is that the claim is small
and literal.
```
to:
```markdown
### Tagline

**Prove your fit**

The tagline is three words and stays three words. Do not extend it to
"Prove your fit, faster" or any variant — the whole point is that the claim is small
and literal.
```

- [ ] **Step 3: Delete the Khmer-review checklist row**

Delete this table row entirely:
```markdown
| 9 | Khmer tagline reviewed by a Khmer first-language speaker | ☐ NOT CHECKED | Person B | The Khmer strings in this file were not written by a Khmer first-language speaker. Plan §1 and §5 Phase 5.1 both require a native review. Treat every Khmer string as provisional until that session happens. |
```

- [ ] **Step 4: Rewrite the Typography section's Khmer rationale**

Change:
```markdown
All three load via `next/font/google` in the locale layout. **Fraunces and IBM Plex Mono have
no Khmer glyphs.** Kantumruy Pro is the only one of the three that covers both scripts, which is
exactly why it — not Fraunces — still carries every word of Khmer UI text. Concretely: the
`font-serif` and `font-mono` Tailwind utilities silently fall back to Kantumruy Pro SemiBold
whenever `<html lang="km">`, via a single rule in `globals.css` (`html[lang="km"] .font-serif,
html[lang="km"] .font-mono { font-family: var(--font-sans); font-weight: 600; letter-spacing:
0; }`). A component author never writes a Khmer-specific class — using `font-serif` or
`font-mono` is enough, and the fallback is automatic and centrally maintained, the same
"inherit by default" pattern the Khmer line-height rule below already uses.

### The Khmer rules — both are non-negotiable

1. **Body line-height ≥ 1.7.** Khmer script stacks subscript consonants (ជើង) below the
   baseline and vowel signs above it. At the 1.4–1.5 line-height that looks correct for Latin
   text, those glyphs are clipped by the line box or collide with the line beneath. Body copy
   uses `leading-[1.75]`. This is a legibility requirement, not a preference — plan §7.4.
2. **Never `text-xs` for Khmer.** At 12px, Khmer diacritics become indistinguishable smudges.
   The floor for Khmer text is `text-sm` (14px), and `text-base` (16px) for anything a user
   has to read rather than glance at. If a design needs `text-xs` to fit, the design is wrong.

Both rules are enforced through a base class applied to Khmer body copy rather than being
re-applied per component, so a new component inherits them by default.

### Numbers

**Numbers stay Arabic numerals (0–9) in both locales.** Not Khmer numerals (០–៩). Khmer
readers read Arabic numerals fluently, and Khmer numerals measurably hurt scanability for
figures like `72%` or `4 months`. Plan §7.5. This applies to coverage percentages, durations,
team sizes, dates, and counts.

### Generated content is not translated

Requirement text, evidence lines, and rewrites are displayed **as-is in English regardless of
the UI locale**, because they are quoted verbatim from an English JD or an English resume.
Translating a quotation would break rule 3's traceability — the highlighted source line must
match the document the user uploaded, character for character. Each such block carries a
subtle "from your resume" / "from the job post" label so the user understands why it did not
switch languages. Plan §7.6.

---

## 5. Khmer verdict vocabulary — FIXED

Plan §7.3: these words are fixed here and used identically in the UI, in exports, and on the
slides. Do not let a translation tool, a teammate, or a later refactor introduce a synonym.
Inconsistent verdict vocabulary is the fastest way to make a bilingual UI read as
machine-translated.

| Verdict | Schema value | English | Khmer | Literal sense |
|---|---|---|---|---|
| Proven | `proven` | Proven | **បានបញ្ជាក់** | "has been confirmed" — the evidence is explicit and cited |
| Partial | `partial` | Partial | **បញ្ជាក់មួយផ្នែក** | "partly confirmed" — adjacent or transferable evidence exists |
| Missing | `missing` | Missing | **គ្មានភស្តុតាង** | "no evidence" — nothing in the resume supports it |

The schema values in column 2 are the `Verdict` literals in `engine/normalize/schema.py`. They
are lowercase English identifiers and never change; only the display strings are localized,
via the i18n keys `results.verdict.proven` / `.partial` / `.missing`.

Note that the Khmer for `missing` is "គ្មានភស្តុតាង" — *no evidence* — and not a word meaning
"failed" or "unqualified". That is deliberate and it matters: a missing verdict is a statement
about the resume, not about the person. The English word carries that neutrality already; the
Khmer had to be chosen to carry it too.

**Pending native review.** Per §2 check 9, these three strings have not been validated by a
Khmer first-language speaker. The Phase 5.1 Khmer QA session (two Khmer-first classmates, not
on the team, 45 minutes) is where they get confirmed or corrected. If they change, they change
here first and then in `web/messages/km.json`.

---
```
to:
```markdown
All three load via `next/font/google` in the root layout.

### Body copy

**Line-height stays relaxed (`leading-[1.75]`) and never drops to `text-xs`.** This is a
general legibility choice for the editorial system, not tied to any particular script.

### Generated content

Requirement text, evidence lines, and rewrites are displayed **exactly as they appear in the
source document** — quoted verbatim from the JD or resume. Each such block carries a subtle
"from your resume" / "from the job post" label so the user understands it's a direct quote.

---
```

- [ ] **Step 5: Fix the last remaining Khmer-language reference in the voice/tone section**

Change:
```markdown
- **Use plain words in both languages.** If the Khmer needs a loan word to stay clear, use the
  loan word.
```
to:
```markdown
- **Use plain words.** If a technical term needs a loan word to stay clear, use the loan word.
```

- [ ] **Step 6: Confirm no remaining Khmer references**

Run: `grep -in "khmer\|km\.json\|next-intl" BRAND.md`
Expected: no output, or only the brand-name-pronunciation line in §1's naming rationale ("a Khmer speaker and an English speaker pronounce it the same way"). That line documents why the *name* "Proofit" was picked — naming history, not a live product-language requirement — and is out of this plan's scope; leave it if it appears.

- [ ] **Step 7: Full-repo verification**

Run all of the following from the repo root and confirm every one succeeds / prints no output:

```bash
grep -rln "next-intl" . --include="*.ts" --include="*.tsx" --include="*.json" --exclude-dir=node_modules --exclude-dir=.next
find web/app -iname "*locale*"
cd web && npx tsc --noEmit && npm run lint && npm run build && cd ..
.venv/bin/pytest tests/ -q
```

- [ ] **Step 8: Commit**

```bash
git add BRAND.md
git commit -m "docs: remove Khmer content from BRAND.md now that the app is English-only"
```

---

## Out of scope (flag to the user, don't do silently)

- `PERSON_B_PLAN_v2.md` still lists bilingual Khmer/English as a "Locked Decision" (§0) and describes Khmer QA, translation, and vocabulary work across Phases 0, 5, and 7, and all of §7 ("i18n Rules"). This plan does not edit that document — it's the semester planning doc that may matter for the FYP defense narrative, and rewriting it is a documentation/strategy decision, not a code change. Recommend the user do a separate pass over it (or annotate it) once this plan lands.
- `PROJECT_SPEC.md` may also reference bilingual UI as a requirement — not read/audited by this plan; worth a quick check.
- `docs/errors.md`'s error matrix may describe "bilingual message" per error code in prose — not code, left untouched.
