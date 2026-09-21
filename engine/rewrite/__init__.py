"""Rewrite — F5: hidden strengths, evidence-bound rewriting, hallucination validator.

OWNER: **Person B** (PERSON_B_PLAN_v2.md §2 "You own":
``engine/rewrite/`` — F5: hidden-strengths detector, rewrite generator,
**hallucination validator**, rejection log).

Built in **Phase 3**, not now. This package is intentionally empty at Phase 0/1:
nothing imports it yet, and there are no stubs here, because a stub would imply a
contract that has not been designed. ``__init__.py`` exists only so the package in
``pyproject.toml``'s ``[tool.setuptools] packages`` list resolves and
``engine/rewrite/forbidden.json`` ships inside the wheel.

What will live here, and the constraints it is already bound by:

* **Hidden-strengths detector** — finds requirements the resume already satisfies
  but phrases badly, and emits
  :class:`~engine.normalize.schema.HiddenStrength` records.
* **Rewrite generator** — writes ``suggested_phrasing`` from the
  :class:`~engine.normalize.schema.Evidence` records *only*: never from the raw
  resume, never from the job description. Rewriting toward the JD's wording is how
  this feature would become a lying machine.
* **Hallucination validator** — every claim in ``suggested_phrasing`` must trace to
  an id in ``facts_used``. ``HiddenStrength._cites_its_own_evidence`` already
  enforces the weakest form of this at parse time; the real validator is stricter
  and rejects generations that invent numbers, titles, tools or durations.
* **Rejection log** — every rejected generation is recorded, because the rejection
  rate is a *result* the evaluation chapter reports, not an error to hide.

Nothing in here is on the ``api/`` contract path. The five callables that cross the
Person A / Person B boundary are listed in engine/README.md, and none of them is
here — F5 output reaches the UI as ``Match.hidden_strengths``.
"""

from __future__ import annotations

from engine.rewrite.detector import detect_hidden_strengths
from engine.rewrite.generator import generate_rewrite
from engine.rewrite.rejection_log import clear_rejection_logs, get_rejection_logs, log_rejection
from engine.rewrite.validator import ValidationResult, validate_rewrite

__all__ = [
    "detect_hidden_strengths",
    "generate_rewrite",
    "validate_rewrite",
    "ValidationResult",
    "log_rejection",
    "get_rejection_logs",
    "clear_rejection_logs",
]
