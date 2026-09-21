"""Match — comparing a normalized job against a normalized resume.

OWNER: **Person A** (PERSON_B_PLAN_v2.md §2 "Person A owns": embedding shortlist,
LLM judge, F4 rules, coverage, realism, TF-IDF baseline).

Schema against schema, never text against text (PROJECT_SPEC.md §6). Both inputs
arrive already normalized by :mod:`engine.normalize`, so nothing in here ever sees
a PDF or an HTML page.

Two callables cross the ownership boundary (§2 contract 2): :func:`run_match` and
:func:`run_baseline`. ``api/`` calls those two and nothing else in here
(engine/README.md, "The internals rule").

The pairing is deliberate. :func:`run_baseline` exists to be beaten: it is the
comparison column in the Phase 6 evaluation chapter and the "Compare with keyword
baseline" toggle on the results screen — the one control that makes the argument
visible instead of narrated.
"""

from __future__ import annotations

from engine.normalize.schema import BaselineMatch, Job, Match, Resume

__all__ = ["run_baseline", "run_match"]


def run_match(job: Job, resume: Resume) -> Match:
    """Produce the full requirement-coverage analysis of one resume against one job."""
    from .matcher import run_match_engine
    return run_match_engine(job, resume)


def run_baseline(job: Job, resume: Resume) -> BaselineMatch:
    """Run the TF-IDF keyword-overlap baseline on the same pair."""
    from .baseline import run_baseline_tfidf
    return run_baseline_tfidf(job, resume)
