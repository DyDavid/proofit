### Task 5: Priority Actions rail — verify, and record CP3's blockers


Most of this landed in Phase 2. This task confirms what exists against the plan's wording and closes only genuine gaps.

**Files:** Modify `web/components/results/ResultsInteractive.tsx` (only if a gap is found); modify `docs/progress-log.md`

- [ ] **Step 1: Verify against the spec.** `PERSON_B_PLAN_v2.md` Phase 4 task 6 asks for two things: each action links to the requirement row it addresses, and `coverage_gain` renders as "+8% required coverage". Read `ResultsInteractive.tsx:337-370` and confirm both. Confirm the anchor actually opens the target row's `<details>` and scrolls to it (the `openRequirement` helper), and that an action with a null `requirement_id` degrades to plain text rather than a dead button.

- [ ] **Step 2: Close any gap found, or record that there is none.** Do not rewrite working code to look different. If both requirements already hold, say so in the report file and make no code commit for this task.

- [ ] **Step 3: Record CP3's blockers.** Append a short, dated section to `docs/progress-log.md` stating precisely why Phase 4 task 7 could not be executed: `engine.match.run_match` and `run_baseline` still raise `NotImplementedError` (CP2 never happened), and no live deployment exists, so "5 real pairs end-to-end on the live URL" has neither an engine nor a URL. List what becomes unblocked the moment each arrives.

- [ ] **Step 4: Commit** — `docs: record Phase 4 completion state and CP3's blockers`
