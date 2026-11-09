"""F5 — hidden-strengths detector (PERSON_B_PLAN_v2.md §5 Phase 3 task 3).

For every requirement the match engine scored `partial` or `missing`, asks one
LLM call whether any evidence record satisfies it despite how the resume
phrases it. One call per requirement, not one call for the whole resume, so
each judgement is auditable on its own and a single bad call cannot silently
swallow every candidate.
"""

from __future__ import annotations

import concurrent.futures

from pydantic import ValidationError

from engine.normalize.schema import Match, Requirement, Resume
from engine.rewrite import llm, prompts
from engine.rewrite.models import HiddenStrengthCandidate

__all__ = ["detect_hidden_strengths"]

_CANDIDATE_VERDICTS = ("partial", "missing")


def _detect_candidate_for_requirement(
    requirement: Requirement,
    evidence_lines: list[str],
    known_evidence_ids: set[str],
) -> HiddenStrengthCandidate | None:
    try:
        response = llm.call_structured(
            system=prompts.DETECT_SYSTEM_PROMPT,
            user=prompts.build_detect_user_prompt(requirement.text, evidence_lines),
            tool_name=prompts.DETECT_TOOL_NAME,
            tool_description="Report whether any evidence record satisfies the requirement.",
            tool_schema=prompts.DETECT_TOOL_SCHEMA,
        )
        if not response.get("found"):
            return None
        evidence_id = response.get("evidence_id")
        if evidence_id not in known_evidence_ids:
            return None

        return HiddenStrengthCandidate(
            requirement_id=requirement.id,
            evidence_id=evidence_id,
            rationale=response.get("rationale") or "",
        )
    except (ValidationError, Exception):
        return None


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
    if match.job is None or not match.job.requirements:
        return []

    known_evidence_ids = {e.id for e in resume.evidence}
    evidence_lines = [prompts.format_evidence_line(e) for e in resume.evidence]

    target_requirements: list[Requirement] = []
    for result in match.results:
        if result.verdict not in _CANDIDATE_VERDICTS:
            continue
        requirement = next((r for r in match.job.requirements if r.id == result.requirement_id), None)
        if requirement is not None:
            target_requirements.append(requirement)

    if not target_requirements:
        return []

    if len(target_requirements) == 1:
        cand = _detect_candidate_for_requirement(target_requirements[0], evidence_lines, known_evidence_ids)
        return [cand] if cand is not None else []

    max_workers = min(4, len(target_requirements))
    candidates: list[HiddenStrengthCandidate] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_detect_candidate_for_requirement, req, evidence_lines, known_evidence_ids)
            for req in target_requirements
        ]
        for fut in futures:
            try:
                candidate = fut.result()
                if candidate is not None:
                    candidates.append(candidate)
            except Exception:
                continue

    return candidates
