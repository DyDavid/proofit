"""Proofit — the analysis engine.

Proofit performs *requirement coverage analysis* for Cambodian entry-level
candidates: it normalizes a job description and a resume into the one schema
(``engine.normalize.schema``) and then compares schema against schema, never
text against text (PROJECT_SPEC.md §6).

This package is deliberately import-light. Importing ``engine`` pulls in nothing
but this docstring and ``__version__`` — no pydantic, no HTTP client, no parser.
That matters because ``api/`` runs on a 512 MB Render free instance
(PERSON_B_PLAN_v2.md §9), and because ``scripts/export_schema.py`` and the CI
staleness check should not pay for the whole engine to read a version string.

Import what you actually need, from the subpackage that owns it::

    from engine.normalize.schema import Job, Match, Resume
    from engine.match import run_match

Subpackage ownership (PERSON_B_PLAN_v2.md §2) is documented in engine/README.md:

    engine.normalize   Person A   schema + JD/resume normalizers
    engine.match       Person A   shortlist, LLM judge, F4 rules, TF-IDF baseline
    engine.ingest      Person A   URL fetch, ATS clients, content-hash cache
    engine.rewrite     Person B   F5 hidden strengths + hallucination validator
    engine.country     Person B   F6 country rules config + visa signal

The five callables that cross the ownership boundary are listed in
engine/README.md. ``api/`` calls only those, and never reaches into internals.
"""

from __future__ import annotations

#: Engine version. Kept in step with ``[project] version`` in pyproject.toml, and
#: recorded on every ``Match`` as ``engine_version`` so the Phase 6 evaluation
#: chapter can state exactly which engine produced each row.
__version__ = "0.1.0"

__all__ = ["__version__"]
