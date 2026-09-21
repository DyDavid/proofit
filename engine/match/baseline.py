"""TF-IDF keyword overlap baseline algorithm.

OWNER: Person A (Dy David)

Serves as the control condition (scikit-learn TF-IDF keyword matcher)
that exists to be beaten in the evaluation chapter and the frontend baseline toggle.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter

from engine.normalize.schema import (
    BaselineMatch,
    BaselineResult,
    Job,
    Resume,
    Verdict,
)

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lower-case words, dropping punctuation."""
    return re.findall(r"\b\w+\b", text.lower())


def _compute_tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tokens)
    total = max(1, len(tokens))
    vec: dict[str, float] = {}
    for term, count in tf.items():
        vec[term] = (count / total) * idf.get(term, 1.0)
    return vec


def _vector_cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    common_terms = set(vec_a.keys()) & set(vec_b.keys())
    if not common_terms:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common_terms)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def run_baseline_tfidf(job: Job, resume: Resume) -> BaselineMatch:
    """Run TF-IDF keyword overlap baseline on job & resume."""
    try:
        # Build candidate resume document
        resume_docs = [ev.source_line for ev in resume.evidence]
        resume_tokens = _tokenize(" ".join(resume_docs))
        resume_terms_set = set(resume_tokens)

        # Build Document Frequencies
        all_docs = resume_docs + [r.text for r in job.requirements]
        doc_count = max(1, len(all_docs))
        df: Counter[str] = Counter()
        for doc in all_docs:
            df.update(set(_tokenize(doc)))

        idf = {term: math.log((1 + doc_count) / (1 + count)) + 1.0 for term, count in df.items()}

        resume_vec = _compute_tfidf_vector(resume_tokens, idf)

        results: list[BaselineResult] = []
        total_v_score = 0.0

        for req in job.requirements:
            req_tokens = _tokenize(req.text)
            req_vec = _compute_tfidf_vector(req_tokens, idf)

            sim_score = round(_vector_cosine(req_vec, resume_vec), 3)

            matched_terms = sorted(list(set(req_tokens) & resume_terms_set))

            verdict_val: Verdict
            if sim_score >= 0.35:
                verdict_val = "proven"
                v_score = 1.0
            elif sim_score >= 0.12:
                verdict_val = "partial"
                v_score = 0.5
            else:
                verdict_val = "missing"
                v_score = 0.0

            total_v_score += v_score

            results.append(
                BaselineResult(
                    requirement_id=req.id,
                    verdict=verdict_val,
                    score=min(1.0, max(0.0, sim_score)),
                    matched_terms=matched_terms,
                )
            )

        cov_score = round((total_v_score / max(1, len(job.requirements))) * 100.0, 1)

        return BaselineMatch(
            method="tfidf",
            coverage_score=cov_score,
            results=results,
        )

    except Exception as err:
        logger.warning("Baseline TF-IDF failed: %s", err)
        return BaselineMatch(
            method="tfidf",
            coverage_score=50.0,
            results=[],
        )
