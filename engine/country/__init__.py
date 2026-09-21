"""Country — F6: cross-border rules config and visa-signal handling.

OWNER: **Person B** (PERSON_B_PLAN_v2.md §2 "You own":
``engine/country/`` — F6 country-rules config loader + visa-signal extraction,
shared with Person A: B owns the config, A owns the extraction prompt if they have
time — **decided at Checkpoint 2**).

Built in **Phase 4**, not now. This package is intentionally empty at Phase 0/1:
nothing imports it yet, and there are no stubs here, because a stub would imply a
contract that has not been designed. ``__init__.py`` exists only so the package in
``pyproject.toml``'s ``[tool.setuptools] packages`` list resolves and
``engine/country/rules.json`` ships inside the wheel.

What will live here:

* **``rules.json``** — per-destination rules for the markets a Cambodian
  entry-level candidate actually applies to (KH, SG, JP, AU, and ``REMOTE``):
  degree-recognition notes, language expectations, and what a visa sponsorship
  signal is worth in that market. Config, not code, so it can be corrected without
  a deploy and cited in the report.
* **Config loader** — reads and validates that file once at import time.
* **Visa-signal handling** — reads :attr:`Job.sponsors_visa`
  (``yes`` / ``no`` / ``unstated``) together with
  :attr:`Job.sponsors_visa_source_line`. Two rules the UI depends on:
  ``unstated`` is the honest default — silence in a job post is not a "no" — and
  the verdict is never shown without the verbatim JD sentence that triggered it. A
  bare yes/no/unstated is not defensible on screen (Phase 4.5).

Nothing in here is on the ``api/`` contract path. The five callables that cross the
Person A / Person B boundary are listed in engine/README.md, and none of them is
here.
"""

from engine.country.loader import CountryRules, get_country_rules, load_all_country_rules

__all__ = ["CountryRules", "get_country_rules", "load_all_country_rules"]
