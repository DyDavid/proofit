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
    """Produce the full requirement-coverage analysis of one resume against one job.

    CONTRACT (PERSON_B_PLAN_v2.md §2, "The contract between you", item 2)::

        engine.match.run_match(job: Job, resume: Resume) -> Match

    Owned by **Person A**. Person B calls it from the analysis BackgroundTask in
    ``api/`` and never reaches into this package's internals.

    Args:
        job: A normalized :class:`~engine.normalize.schema.Job` from
            :func:`engine.normalize.normalize_jd`.
        resume: A normalized :class:`~engine.normalize.schema.Resume` from
            :func:`engine.normalize.normalize_resume`.

    Returns:
        A validated :class:`~engine.normalize.schema.Match`, with ``job`` and
        ``resume`` embedded so the stored match is self-contained. Required of it:

        * **One verdict per requirement, and every requirement gets one** — even
          when that verdict is ``missing``. ``Match._references_resolve`` raises if
          any requirement is left without one.
        * **Every verdict is traceable** (PROJECT_SPEC.md §9 rule 3). ``proven`` and
          ``partial`` must cite at least one ``evidence_ids`` entry; ``missing`` must
          cite none and must carry an explicit ``missing_reason``. Enforced by
          ``MatchResult._traceable`` at parse time.
        * **No scope inflation** (§9 rule 2 / F4). An ``experience`` requirement may
          not be ``proven`` by coursework, a project, a competition or volunteering
          alone — ``partial`` is exactly what those records are for. Enforced by
          ``Match._enforce_no_scope_inflation``.
        * ``coverage_score`` weights required over preferred; ``coverage_required_only``
          is the honest headline number. Both are percentages, 0–100.

        Not a score — a verdict, with its receipt.

    Progress:
        The UI renders a four-step stepper. Emit
        :data:`~engine.normalize.schema.MatchStage` values
        (``reading_resume`` → ``reading_job`` → ``matching_requirements`` →
        ``checking_realism``) through a progress hook where possible; the UI falls
        back to timed fake stages when ``stage`` is null.

    Raises:
        NotImplementedError: Always, until Person A lands the implementation. The
            schema it returns locks at **Checkpoint 1** (end of Week 3); the API
            switches from fixtures to this function at **Checkpoint 2** (end of
            Week 7).

    Fixture:
        ``data/fixtures/`` holds a golden ``Match`` for this function
        (§2 contract 3). Screens are built against the fixture first, live engine
        second — that is why Phase 1 is not blocked on this file.
    """
    raise NotImplementedError(
        "engine.match.run_match is Person A's to implement (PERSON_B_PLAN_v2.md §2, "
        "contract 2); the Match schema it returns locks at Checkpoint 1, end of Week 3. "
        "Until Checkpoint 2 wires the live engine, run the API with ENGINE_MODE=mock, "
        "which serves the golden Match fixture from data/fixtures/."
    )


def run_baseline(job: Job, resume: Resume) -> BaselineMatch:
    """Run the TF-IDF keyword-overlap baseline on the same pair.

    CONTRACT (PERSON_B_PLAN_v2.md §2, "The contract between you", item 2)::

        engine.match.run_baseline(job: Job, resume: Resume) -> BaselineMatch

    Owned by **Person A**. Person B calls it from the analysis BackgroundTask in
    ``api/`` and never reaches into this package's internals.

    This is the control condition. It exists so the project can *show* that
    schema-level matching beats keyword overlap, rather than assert it: the
    ``BaselineMatch`` is returned alongside the ``Match`` on
    ``GET /api/analyses/{id}`` and drives the results screen's
    "Compare with keyword baseline" toggle and the evaluation chapter's comparison
    column.

    Args:
        job: The same normalized :class:`~engine.normalize.schema.Job` passed to
            :func:`run_match`.
        resume: The same normalized :class:`~engine.normalize.schema.Resume` passed
            to :func:`run_match`.

    Returns:
        A validated :class:`~engine.normalize.schema.BaselineMatch`: ``method``
        fixed at ``"tfidf"``, a ``coverage_score`` percentage (0–100) computed the
        naive way, and one :class:`~engine.normalize.schema.BaselineResult` per
        requirement carrying the cosine ``score`` of the TF-IDF vectors and the
        ``matched_terms`` that produced it. It must be run on the *same* pair as
        :func:`run_match`, or the comparison is not a comparison.

    Raises:
        NotImplementedError: Always, until Person A lands the implementation. The
            schema it returns locks at **Checkpoint 1** (end of Week 3); the API
            switches from fixtures to this function at **Checkpoint 2** (end of
            Week 7).

    Fixture:
        ``data/fixtures/`` holds a golden ``BaselineMatch`` for this function
        (§2 contract 3), paired with the golden ``Match`` so the toggle can be built
        and screenshotted before the live engine exists.
    """
    raise NotImplementedError(
        "engine.match.run_baseline is Person A's to implement (PERSON_B_PLAN_v2.md §2, "
        "contract 2); the BaselineMatch schema it returns locks at Checkpoint 1, end of "
        "Week 3. Until Checkpoint 2 wires the live engine, run the API with "
        "ENGINE_MODE=mock, which serves the golden BaselineMatch fixture from "
        "data/fixtures/."
    )
