# Proofit — Brand

> Phase 0, task 1 (`PERSON_B_PLAN_v2.md` §5). This file is the single source of
> truth for the product name and the colour tokens.

---

## 1. Name

**Proofit**

Pronounced *proof-it*. One word, capital P, no space, no hyphen. Never "ProofIt",
never "Proof It", never "PROOFIT" outside of a wordmark lockup.

### Tagline

**Prove your fit**

The tagline is three words and stays three words. Do not extend it to
"Prove your fit, faster" or any variant — the whole point is that the claim is small
and literal.

### Positioning

Proofit is requirement coverage analysis for Cambodian entry-level candidates. It reads
a job description from a local board, a pasted URL, or pasted text, normalizes both that
job post and the candidate's resume into one schema, and then returns a verdict for every
single requirement — proven, partial, or missing — with the exact resume line that
justifies it. It is built for people who have coursework, class projects, and part-time
work instead of an employment history, because that is what a fresh graduate in Phnom Penh
actually has, and because every mainstream tool returns "Missing" on all of it. It works
for local roles and for applications to Singapore, Japan, Australia, and remote-US, adapting
its output to the destination country's resume conventions. It does not score you; it shows
you which requirements you can already prove and which ones you cannot.

### Why this name

**Proof + fit.** The product's one non-negotiable rule is that every verdict is traceable
(`PROJECT_SPEC.md` §9 rule 3): a verdict cannot exist without either a cited `evidence_id`
or an explicit missing reason, and `engine/normalize/schema.py` enforces that at parse time
rather than in a prompt. "Proof" names that rule. "Fit" names the output — requirement
coverage, not a keyword score. The name therefore encodes the two things that distinguish
this project from Teal, Jobscan, and Rezi, which is exactly what a brand name should do when
the examiner asks why it is called that.

It also survives the two practical tests: an examiner who has never heard it can spell it
after hearing it once, and a Khmer speaker and an English speaker pronounce it the same way.

`PERSON_B_PLAN_v2.md` §1 lists Proofit as candidate #4 and recommends "Spean" as the
author's own pick. The team chose Proofit. The plan document's remaining uses of "Spean"
are placeholder text; **the name is Proofit everywhere in this repo.**

### Logo

No logo has been designed. The placeholder — sufficient for Phase 0 per plan §5 task 1 — is
a **wordmark**: the word `Proofit` set in Fraunces italic, `--color-ink` on `--color-paper`
(revised 12 Sep 2026 alongside §3/§4 — see the Fraunces italic treatment there; the logo is
plain ink, not the lac accent, matching the header's own text colour). No icon, no mark, no
gradient. If a mark is ever drawn, it belongs in `docs/brand/` and this section gets rewritten.

---

## 2. Before you commit the name — NOT YET VERIFIED

**None of the checks below have been performed.** They are listed here so that nobody
assumes the name is legally or commercially clear. As of this writing the name has been
chosen for the project and the repo only. It has not been registered, searched, or reserved
anywhere. "Proofit" is a plausible-sounding English word and `PERSON_B_PLAN_v2.md` §1
explicitly warns that it "may exist" as an existing trademark.

| # | Check | Status | Who | Notes |
|---|---|---|---|---|
| 1 | `proofit.com` availability | ☐ NOT CHECKED | Person B | Almost certainly taken. Assume so until proven otherwise. |
| 2 | `proofit.app` availability | ☐ NOT CHECKED | Person B | Plan §5 task 1 says register a domain in Week 1. Not done. |
| 3 | `proofit.kh` / `.com.kh` availability | ☐ NOT CHECKED | Person B | `.kh` registration in Cambodia goes through an accredited registrar and asks for documentation; budget time. |
| 4 | Cambodian trademark search (MoC DIP) | ☐ NOT CHECKED | Person B | Ministry of Commerce, Department of Intellectual Property. |
| 5 | International trademark search (WIPO / USPTO) | ☐ NOT CHECKED | Person B | For an existing "Proofit" in class 9 / 42 software. |
| 6 | Instagram `@proofit` | ☐ NOT CHECKED | Person B | |
| 7 | Facebook page name | ☐ NOT CHECKED | Person B | The dominant social platform for the Cambodian audience. |
| 8 | GitHub org / repo name | ☐ NOT CHECKED | Person B | Repo is currently a local git repo only. |

**Consequence if a check fails:** a rename is a find-and-replace across `web/messages/*.json`,
this file, `README.md`, and the slides. It is cheap now and expensive after Week 12's feature
freeze. Do checks 4 and 5 before printing anything.

---

## 3. Colour tokens

Tokens are defined **once**, in `web/app/globals.css` inside the Tailwind v4 `@theme` block.
There is no `tailwind.config.ts` in this project — Tailwind v4 does not use one, and creating
one would fork the source of truth. Never hard-code a hex in a component; use the token.

> **Revision (12 Sep 2026):** the indigo/slate/emerald-amber-red system this section originally
> specified is retired. Person B's own design reference — a working prototype built before this
> file existed — used a warm paper-and-ink editorial system instead, and that is the system the
> product should actually look like. This section now documents that system as the fixed source
> of truth. Any component still using `brand-*`, `slate-*`, or the old `proven/partial/missing`
> hexes is out of date and must be migrated, not treated as a second valid option.

### Paper and ink — the base palette

Not a grey ramp. Warm off-white paper, warm near-black ink. Nothing in this system is pure
white or pure black.

| Token | Hex | Use |
|---|---|---|
| `--color-paper` | `#F3EEE4` | Page background |
| `--color-paper-2` | `#EAE3D5` | Section-level alternation (e.g. the differentiator band) |
| `--color-paper-3` | `#E0D7C4` | Recessed surfaces: input tracks, inset wells |
| `--color-surface-raised` | `#FBF8F1` | Card and panel face — lighter than the page, not white |
| `--color-ink` | `#1B1915` | Primary text, headings |
| `--color-ink-2` | `#4A453C` | Secondary text, body copy on muted surfaces |
| `--color-ink-3` | `#6D675A` | Tertiary text: captions, timestamps, hints. Adjusted from the prototype's `#7A7364`, which read at 4.07:1 on `--paper` — under AA. This shade clears 4.86:1. |
| `--color-rule` | `#CFC6B2` | Borders and dividers only — never text |

### Brand / accent — lacquer red

There is no separate "brand blue." The one accent colour doubles as the `missing` verdict —
this is deliberate, not a collision: red is both "pay attention" and "nothing proves this yet,"
and reusing the hue means the whole UI has exactly one urgent colour instead of two competing
ones.

| Token | Hex | Use |
|---|---|---|
| `--color-lac` | `#B4301C` | Primary button fill, active emphasis, italic accent word in headlines |
| `--color-lac-2` | `#8F2415` | Hover/pressed state of the primary button |
| `--color-lac-tint` | `#F2DCD5` | Tinted background behind lac/missing content |

### Verdict — proven (forest green)

| Token | Hex | Use |
|---|---|---|
| `--color-proven` | `#2C6B3F` | Icon, badge text, tile swatch — 5.53:1 on paper, safe as text |
| `--color-proven-tint` | `#DDE9DB` | Row/badge background |

### Verdict — partial (olive)

| Token | Hex | Use |
|---|---|---|
| `--color-partial` | `#9A6A08` | Tile swatch, icon fill (non-text; see below) |
| `--color-partial-ink` | `#8A5F07` | **Text only.** The prototype's `#9A6A08` measures 4.09:1 on paper — under AA. This shade clears 4.88:1. |
| `--color-partial-tint` | `#F1E4C0` | Row/badge background |

### Verdict — missing (same red as the accent)

| Token | Hex | Use |
|---|---|---|
| `--color-missing` | `#B4301C` | Same value as `--color-lac` — see above |
| `--color-missing-tint` | `#F2DCD5` | Same value as `--color-lac-tint` |

### Highlight

| Token | Hex | Use |
|---|---|---|
| `--color-hl` | `#F4E27E` | Background behind a `<mark>`-highlighted resume excerpt only |

**`--color-partial` is for icons, tile swatches, and other non-text fills; use
`--color-partial-ink` for the word itself.** Every other verdict/accent colour in this table
already clears 4.5:1 as text on both `--paper` and `--color-surface-raised`, so only partial
needs the split. This is the same discipline the retired indigo system had — verified again
here, not assumed carried over.

### Shape

Content surfaces are sharp-cornered; only interactive controls get a pill. This split — not a
uniform radius — is what makes the system read as stationery rather than as a generic app.

| Token | Value | Use |
|---|---|---|
| `--radius-card` | `0` | Cards, panels, the dropzone, inputs, textareas |
| `--radius-control` | `0` | Same as card — inputs and textareas are sharp, not rounded |
| `--radius-tag` | `3px` | Verdict pills, the realism stamp, tile swatches |
| `--radius-pill` | `9999px` | Buttons, chips, the language segmented control, the toggle switch |

**A verdict is never communicated by colour alone.** Every verdict displays an inline SVG
icon *and* the verdict word, always. Icons live as small local components in
`web/components/ui/VerdictIcon.tsx`; no icon library is a dependency of this project.

| Verdict | Icon | Colour role |
|---|---|---|
| proven | check-circle | `--color-proven` text and icon |
| partial | half-filled circle | `--color-partial-ink` text, `--color-partial` icon |
| missing | x-circle | `--color-missing` text and icon |

The reason is not only accessibility compliance. Roughly 1 in 12 men has a red–green colour
vision deficiency, and proven/missing is precisely a green/red pair. An examiner who cannot
distinguish them from colour must still be able to read the screen.

---

## 4. Typography

**Three typefaces, one per role — revised 12 Sep 2026 alongside §3.** The original version of
this section specified Kantumruy Pro alone, matching the retired indigo system's plainer look.
The paper-and-ink system needs the editorial contrast a single sans can't give it:

| Role | Font | CSS variable | Used for |
|---|---|---|---|
| Display | Fraunces | `--font-serif` | Headlines, the big coverage numbers, pull-quotes |
| Body / UI | Kantumruy Pro | `--font-sans` | Everything else: body copy, buttons, nav, form controls |
| Data / label | IBM Plex Mono | `--font-mono` | Eyebrows, timestamps, verdict pills, stamps, confidence figures |

All three load via `next/font/google` in the root layout.

### Body copy

**Line-height stays relaxed (`leading-[1.75]`) and never drops to `text-xs`.** This is a
general legibility choice for the editorial system, not tied to any particular script.

### Generated content

Requirement text, evidence lines, and rewrites are displayed **exactly as they appear in the
source document** — quoted verbatim from the JD or resume. Each such block carries a subtle
"from your resume" / "from the job post" label so the user understands it's a direct quote.

---

## 6. Voice and tone

Proofit's voice is **honest, specific, and unimpressed by itself.** The product's entire
credibility rests on not overclaiming, so the copy cannot overclaim either.

### Always

- **Say what the evidence shows, and where it came from.** "Your class project (4 months, team
  of 4) counts as partial evidence for a 2-year experience requirement." Concrete, sourced,
  and it tells the user the limit of the claim in the same breath as the claim.
- **Name the gap plainly.** A missing requirement is called missing. Softening it into
  "opportunity" or "area to develop" wastes the user's time — they are about to spend an hour
  on an application and they need to know.
- **Treat non-work evidence as real evidence, without inflating it.** A project is a project.
  It is worth something. It is not a job.
- **Address the user directly**, second person. "You can prove 7 of 11 requirements."
- **Use plain words.** If a technical term needs a loan word to stay clear, use the loan word.

### Never

- **Never say "beat the ATS", "ATS score", "ATS-optimized", or "pass the ATS."** This is a
  hard rule from `PROJECT_SPEC.md` §2, not a style preference. Most real ATS platforms —
  Workday, Greenhouse, Taleo — do not AI-score resumes; recruiters run keyword searches
  against them. The framing is indefensible and an examiner may know it. The correct framing
  is always **"requirement coverage analysis."**
- **Never imply the product invents, adds, or improves experience.** It rephrases what is
  already in the resume, from the evidence records only. `PROJECT_SPEC.md` §9 rules 1 and 2.
  Copy that says "make your experience stronger" is a lie about how the system works.
- **Never upgrade a class project into employment in any string**, including examples,
  placeholder text, and marketing copy. If the copy would fail the F5 validator, do not ship it.
- **Never promise an outcome.** Not "get hired", not "land the job", not "guaranteed". Proofit
  tells you what you can prove. It does not know who will hire you.
- **Never claim to be Cambodia-only or to be limited to Cambodia.** The framing is
  "Cambodia-based, not Cambodia-limited": the users are Cambodian, the job targets are global.
- **Never disparage a competitor with a false claim.** Specifically, do not say "Teal is
  USA-only" — it is a web app anyone can sign up for. The accurate claims are that its
  supported boards include zero Cambodian sources, its resume conventions are US-default, its
  matching is keyword-based, and it assumes prior employment. `PROJECT_SPEC.md` §2.

### The onboarding strip, as the tone reference

Three lines on the Analyze screen (plan §5 Phase 5.6) state what the tool does and does not
do. When any other copy is in doubt, match this register:

> Proofit checks your resume against each requirement in a job post, one by one.
> It uses only what is already in your resume — it never invents experience.
> It is not an "ATS score". It shows you which requirements you can prove.

---

*Last updated 10 Sep 2026 · Owner: Person B · Companion to `PROJECT_SPEC.md` and `PERSON_B_PLAN_v2.md`*
