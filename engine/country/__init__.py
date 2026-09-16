"""Country — F6: cross-border rules config and visa-signal handling.

OWNER: **Person B** (PERSON_B_PLAN_v2.md §2 "You own":
``engine/country/`` — F6 country-rules config loader + visa-signal extraction,
shared with Person A: B owns the config, A owns the extraction prompt if they have
time — **decided at Checkpoint 2**).

Built in **Phase 4** (PERSON_B_PLAN_v2.md §5 Phase 4 task 4).

What is here now:

* **``rules.json``** — per-destination rules for the markets a Cambodian
  entry-level candidate actually applies to: ``KH``, ``SG``, ``JP``, ``AU`` and
  ``REMOTE`` (the United States remote market). Page length, photo expectation,
  personal details to include and to leave out, date format, section order, tone
  notes, and the work-authorisation vocabulary to look for in that market's job
  posts. Config, not code, so it can be corrected without a deploy and cited in
  the report.
* **``rules.py``** — the Pydantic model, a cached loader, and
  :func:`~engine.country.rules.rules_for`, which resolves any of this codebase's
  three spellings of a destination (the browser's ``"usRemote"``, the schema's
  ``"REMOTE"``, the plan's prose "US-remote") onto one rule set. The UI's sixth
  option, ``"other"``, resolves to ``None`` by design: no rules is a normal
  outcome, not a failure.

What is still to come, in Phase 4 task 5:

* **Visa-signal handling** — reads :attr:`Job.sponsors_visa`
  (``yes`` / ``no`` / ``unstated``) together with
  :attr:`Job.sponsors_visa_source_line`. Two rules the UI depends on:
  ``unstated`` is the honest default — silence in a job post is not a "no" — and
  the verdict is never shown without the verbatim JD sentence that triggered it. A
  bare yes/no/unstated is not defensible on screen. ``visa_terms`` in
  ``rules.json`` is the vocabulary side of this, ready ahead of the matcher that
  will use it.

Nothing in here is on the ``api/`` contract path. The five callables that cross the
Person A / Person B boundary are listed in engine/README.md, and none of them is
here.
"""

from __future__ import annotations

#: Nothing is re-exported at the package root — import from the submodule that
#: owns it (`engine.country.rules`) rather than `engine.country` directly. Same
#: convention as `engine.rewrite`.
__all__: list[str] = []
