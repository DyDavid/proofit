# Wireframes

> **No wireframes have been drawn yet. This directory contains no images.**
>
> That is the honest current state as of 10 Sep 2026. `PERSON_B_PLAN_v2.md` §5 Phase 0 task 6
> schedules wireframing for Week 2 (14–20 Sep) and the classmate feedback round with it.
> This file exists so that the task has a defined shape, a destination, and a recording format
> before the session happens — not to imply the session has happened.

---

## What goes in this directory

Image files, committed to the repo. Figma frames exported as PNG, or paper sketches
photographed with a phone — the plan permits either, and paper is faster. Resolution matters
less than legibility: a reader must be able to read the labels at 100% zoom.

Naming: `NN-screen-name.png`, numbered in the order a user meets them.

```
docs/wireframes/
├── README.md            ← this file
├── 01-landing.png
├── 02-analyze.png
├── 03-results.png
├── 04-rewrite-panel.png
├── 05-country-selector.png
└── feedback/            ← filled copies of the §3 template, one per classmate
```

If Figma is used, put the share link in §4 below as well. A link alone is not enough — Figma
files move, permissions lapse, and the report needs an image that still exists in December.

---

## The five wireframes required

Plan §5 Phase 0 task 6 names exactly these five. Screens 4 and 5 are panels within Results
rather than separate routes, but they need their own frames because they are the two pieces of
the interface most likely to be confusing on first contact.

### 1. Landing — `/[locale]`

Hero with headline, subtitle, and primary CTA; three differentiator cards (non-work evidence,
local JD reach, cross-border adaptation); a "Try a sample" secondary action; locale switcher in
the header.

**The question this wireframe must answer:** does a visitor understand what the product does
before they scroll? The three cards carry the entire differentiation argument, so their order
and their headings are the thing to test.

### 2. Analyze — `/[locale]/analyze`

Two columns on desktop. Left: resume dropzone (PDF/DOCX, 5 MB). Right: JD input with two tabs,
`Paste text` and `Paste URL`. Below: destination-country select, then the Analyze button,
disabled until both inputs are present. An onboarding strip of three lines stating what the
tool does and does not do sits above the inputs.

**Questions:** Is it obvious that *both* inputs are required? Does the disabled button read as
"not yet" or as "broken"? Does anyone try to type a job title into the JD box instead of
pasting the post?

### 3. Results — `/[locale]/results/[id]`

The screen the examiner will look at longest. Header with job title, company, and realism badge;
two coverage gauges side by side (`coverage_score` and `coverage_required_only`); the requirement
list grouped **Missing → Partial → Proven**, gaps first, with `required` before `preferred`
inside each group; each row expandable to show the cited resume line, the reasoning, and the
evidence-type icon; a Priority Actions rail; and the "Compare with keyword baseline" toggle.

**Questions:** Does gaps-first ordering read as discouraging or as useful? Do two gauges confuse
more than one gauge would inform? Is a `partial` verdict understood as "this counts, partly" or
misread as "this failed"? Does anyone notice the baseline toggle without being pointed at it?

Also sketch the **progress state** of this same route — the four-step stepper shown while
`status` is not `done`. It is a different screen to the user even though it is the same URL.

### 4. Rewrite panel

The Hidden Strengths section: `current_phrasing` on the left, `suggested_phrasing` on the right,
changed words highlighted, `facts_used` chips that expand to the underlying evidence record,
Copy and Reject buttons, and the counter — "3 suggestions passed validation · 1 rejected".

**Questions:** Does anyone believe the tool invented the rewritten line? The `facts_used` chips
exist precisely to answer that, so test whether anyone notices them unprompted. Does the
rejected counter read as a defect in the product, or as evidence that it is careful? If it
reads as a defect, the label is wrong — it is the single strongest proof of rule 1 on screen.

### 5. Country selector

The control plus its consequences: a "Format for {country}" checklist derived from the country
rules, and the visa line showing `sponsors_visa` with the JD sentence it was read from.

**Questions:** Is it clear that changing the country changes the *advice* and not the *match*?
Does the visa line read as a promise from the employer, or as an observation about the job post?
That distinction has real consequences for a user deciding whether to apply abroad.

---

## Classmate feedback round — plan §5 Phase 0 task 6

> "Show them to 3 classmates; note what confused them."

**Not yet done. Zero classmates have seen anything.**

### How to run it

Three classmates, separately — not as a group, because the first person to speak anchors
everyone else. Ten minutes each is enough. Pick people who are actually job-hunting; a
classmate who has never written a resume will not spot what is missing.

Show one wireframe at a time and ask them to **say what they think it does before you explain
anything.** The moment you explain, the data is gone. Your job in the session is to keep quiet
and write down where they hesitate.

The output being sought is not "do you like it" — that produces polite agreement and no
information. It is **what confused them**: where they paused, what they misread, what they
expected to happen and did not, and which word they had to ask about. Note confusion even when
you disagree with it; a confusion you can argue away is still a confusion the examiner may have.

Run at least one of the three sessions **in Khmer**, with a Khmer-first speaker, on the Khmer
labels. This is separate from and earlier than the Phase 5.1 Khmer QA session on the built
product, and it is cheaper to act on: a label that reads badly on paper in Week 2 costs nothing
to change, and the same label in Week 12 is in three files and a slide deck.

### Recording template

Copy this block once per classmate into `docs/wireframes/feedback/NN-initials.md`. Keep the
verbatim quotes — a paraphrase loses the thing that made the quote useful.

```markdown
# Wireframe feedback — [initials]

- **Date:** DD Mon YYYY
- **Language of session:** en / km
- **Year and program:**
- **Currently job-hunting:** yes / no
- **Has applied to a job abroad:** yes / no

## Screen 1 — Landing
- What they said it does, before any explanation:
- Confused by:
- Misread (said X, it means Y):
- Asked about:
- Expected to happen and didn't:
- Verbatim quote worth keeping:

## Screen 2 — Analyze
- What they said it does, before any explanation:
- Confused by:
- Did they understand both inputs are required?  yes / no / needed a hint
- Verbatim quote worth keeping:

## Screen 3 — Results
- What they said it does, before any explanation:
- Confused by:
- How they described a "partial" verdict in their own words:
- Did they notice the baseline toggle unprompted?  yes / no
- Did gaps-first ordering feel useful or discouraging?
- Verbatim quote worth keeping:

## Screen 4 — Rewrite panel
- Did they think the tool invented the rewritten line?  yes / no / unsure
- Did they notice the facts_used chips unprompted?  yes / no
- How they read the "1 rejected" counter — careful, or broken?
- Verbatim quote worth keeping:

## Screen 5 — Country selector
- Did they understand it changes the advice, not the match?  yes / no
- How they read the visa line:
- Verbatim quote worth keeping:

## Overall
- The single most confusing thing in the whole set:
- One thing they'd change:
- Anything they expected the product to do that it doesn't:
```

### After the three sessions

Write a short synthesis at the bottom of this file: every confusion that **two or more** of the
three hit, plus what changed as a result. One person's confusion is noise; two people's is a
design problem. Record the ones you decided *not* to act on and why — that is the more
defensible half of the write-up, and Chapter 4 of the report can use it directly.

---

## Status log

| Item | Status | Date |
|---|---|---|
| 01 Landing wireframe | ☐ Not drawn | — |
| 02 Analyze wireframe | ☐ Not drawn | — |
| 03 Results wireframe (incl. progress state) | ☐ Not drawn | — |
| 04 Rewrite panel wireframe | ☐ Not drawn | — |
| 05 Country selector wireframe | ☐ Not drawn | — |
| Classmate 1 session | ☐ Not run | — |
| Classmate 2 session | ☐ Not run | — |
| Classmate 3 session (Khmer) | ☐ Not run | — |
| Synthesis written | ☐ Not written | — |
| Figma link (if used) | — | — |

Update this table as each item completes. **Do not tick a box in advance.**

---

*Created 10 Sep 2026 · Phase 0 task 6, scheduled for Week 2 · Owner: Person B*
