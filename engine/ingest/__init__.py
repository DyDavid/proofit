"""Ingest — getting a job post out of the internet and into plain text.

OWNER: **Person A** (PERSON_B_PLAN_v2.md §2 "Person A owns": ATS clients,
aggregator, URL path, local board module, content-hash cache).

This package's whole job is text acquisition. It does no normalization: the string
it returns goes straight to :func:`engine.normalize.normalize_jd`, which is what
turns it into a :class:`~engine.normalize.schema.Job`. Keeping the two apart is
what lets the same normalizer serve a pasted post and a scraped one.

One callable crosses the ownership boundary (§2 contract 2): :func:`fetch_jd`.
``api/`` calls that and nothing else in here (engine/README.md, "The internals rule").
"""

from __future__ import annotations

__all__ = ["fetch_jd"]


def fetch_jd(url: str) -> str:
    """Fetch a job post from a URL and return its raw text. Cache-aware.

    CONTRACT (PERSON_B_PLAN_v2.md §2, "The contract between you", item 2)::

        engine.ingest.fetch_jd(url: str) -> str      # raw text, cache-aware

    Owned by **Person A**. Person B calls it from ``api/routes/jobs.py`` on the
    ``{"url": ...}`` branch of ``POST /api/jobs``, then hands the result to
    :func:`engine.normalize.normalize_jd`.

    Args:
        url: The job posting URL, already validated by the API for scheme and host.
            The API rejects anything non-``http(s)`` or pointing at a private /
            loopback address before calling, as ``JOB_URL_BLOCKED``.

    Returns:
        The job post as plain text — boilerplate, navigation and cookie banners
        stripped, the post itself intact. Not a :class:`~engine.normalize.schema.Job`:
        the caller passes this string to :func:`engine.normalize.normalize_jd`.

    Cache:
        "Cache-aware" is the content-hash cache from PROJECT_SPEC.md §9 rule 4 —
        the same URL must not be re-fetched and the same text must not be
        re-normalized, because LLM cost otherwise scales with users. The API
        reports a cache hit to the client as ``{"cached": true}`` on
        ``POST /api/jobs``.

    Raises:
        NotImplementedError: Always, until Person A lands the implementation. The
            API switches from fixtures to this function at **Checkpoint 2** (end of
            Week 7); the schema its output feeds locks at **Checkpoint 1** (end of
            Week 3).
        ValueError: (once implemented) on a blocked host or a robots-disallowed
            path — surfaced by the API as ``JOB_URL_BLOCKED``.
        RuntimeError: (once implemented) on a network failure, a non-2xx response,
            or a page with no extractable post — surfaced as ``JOB_FETCH_FAILED``.

    Fixture:
        ``data/fixtures/`` holds golden raw text for this function (§2 contract 3),
        alongside the 30 hand-collected posts in ``data/jds/``.
    """
    raise NotImplementedError(
        "engine.ingest.fetch_jd is Person A's to implement (PERSON_B_PLAN_v2.md §2, "
        "contract 2); the Job schema its output feeds locks at Checkpoint 1, end of "
        "Week 3. Until Checkpoint 2 wires the live engine, run the API with "
        "ENGINE_MODE=mock, which serves golden job text from data/fixtures/ instead "
        "of touching the network."
    )
