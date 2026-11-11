"""F5 — hidden-strengths detector (PERSON_B_PLAN_v2.md §5 Phase 3 task 3).

For every requirement the match engine scored `partial` or `missing`, asks one
LLM call whether any evidence record satisfies it despite how the resume
phrases it. One call per requirement, not one call for the whole resume, so
each judgement is auditable on its own and a single bad call cannot silently
swallow every candidate.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import ValidationError

from engine.normalize.schema import Match, Resume
from engine.rewrite import llm, prompts
from engine.rewrite.models import HiddenStrengthCandidate

__all__ = ["detect_hidden_strengths"]

_CANDIDATE_VERDICTS = ("partial", "missing")
MAX_DETECT_CHECKS = 3


def detect_hidden_strengths(match: Match, resume: Resume) -> list[HiddenStrengthCandidate]:
    """Find resume evidence that already satisfies a poorly-worded requirement.

    Args:
        match: A `Match` with `job` embedded — `match.job.requirements`
            supplies the requirement text for every `partial`/`missing` result.
            Returns `[]` immediately if `job` is absent.
        resume: The `Resume` whose `evidence` list is offered to the LLM as the
            only source of facts it may point to.

    Returns:
        One `HiddenStrengthCandidate` per requirement where the LLM found a
        satisfying evidence record. A candidate whose `evidence_id` is not a
        real id in `resume.evidence`, or that otherwise fails
        `HiddenStrengthCandidate`'s own validation, is dropped rather than
        trusted — the model inventing an id is a real failure mode, not a
        hypothetical one.
    """
    if match.job is None:
        return []

    known_evidence_ids = {e.id for e in resume.evidence}
    evidence_lines = [prompts.format_evidence_line(e) for e in resume.evidence]

    candidates: list[HiddenStrengthCandidate] = []
    # Filter candidates and prioritize "partial" (which already has some evidence)
    # over "missing", capped to MAX_DETECT_CHECKS to ensure quick response and avoid rate limits.
    candidate_results = [r for r in match.results if r.verdict in _CANDIDATE_VERDICTS]
    candidate_results.sort(key=lambda r: 0 if r.verdict == "partial" else 1)
    candidate_results = candidate_results[:MAX_DETECT_CHECKS]

    def _check_requirement(result: Any) -> HiddenStrengthCandidate | None:
        req = next((r for r in match.job.requirements if r.id == result.requirement_id), None)
        if req is None:
            return None

        response = llm.call_structured(
            system=prompts.DETECT_SYSTEM_PROMPT,
            user=prompts.build_detect_user_prompt(req.text, evidence_lines),
            tool_name=prompts.DETECT_TOOL_NAME,
            tool_description="Report whether any evidence record satisfies the requirement.",
            tool_schema=prompts.DETECT_TOOL_SCHEMA,
        )
        if not response.get("found"):
            return None
        ev_id = response.get("evidence_id")
        if ev_id not in known_evidence_ids:
            return None

        try:
            return HiddenStrengthCandidate(
                requirement_id=req.id,
                evidence_id=ev_id,
                rationale=response.get("rationale") or "",
            )
        except ValidationError:
            return None

    if len(candidate_results) <= 1:
        for result in candidate_results:
            cand = _check_requirement(result)
            if cand is not None:
                candidates.append(cand)
    else:
        with ThreadPoolExecutor(max_workers=min(len(candidate_results), MAX_DETECT_CHECKS)) as executor:
            for cand in executor.map(_check_requirement, candidate_results):
                if cand is not None:
                    candidates.append(cand)

    return candidates
