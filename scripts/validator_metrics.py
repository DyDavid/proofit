#!/usr/bin/env python3
"""Precision/recall table for the F5 rewrite validator's two deterministic
layers (Phase 4 hardening task 2; PROJECT_SPEC.md §9 rules 1-2).

Measures `engine.rewrite.validate.precheck_scope_inflation` and
`precheck_rewrite` — the two zero-cost, zero-network layers — against the 30
labelled cases in `tests/rewrite_cases.py`. It does **not** measure the third
layer, `_call_llm_validator`, by default: doing so would require a live
`ANTHROPIC_API_KEY` and network access, and a table that silently folded a
mocked LLM's verdicts into "the validator's" precision/recall would misreport
what actually runs for free. Every number this script prints without `--live`
comes from regex and a wordlist, nothing else.

Run it directly, from any working directory::

    .venv/bin/python scripts/validator_metrics.py
    .venv/bin/python scripts/validator_metrics.py --live   # also exercises the real LLM

Exits 0 on success (this script performs no assertions of its own — the
dataset's correctness is `tests/test_rewrite_validator.py`'s job; this one
only reports).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable
from pathlib import Path

# The brief's own note applies: `tests/` has no `__init__.py` (a namespace
# package), so `from tests.rewrite_cases import CASES` only resolves once the
# repo root is on sys.path. Running this file directly puts *its own*
# directory (scripts/) on sys.path[0], not the repo root, so that has to be
# added explicitly, before the import below.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engine.normalize.schema import Evidence  # noqa: E402
from engine.rewrite.models import Rewrite  # noqa: E402
from engine.rewrite.validate import (  # noqa: E402
    precheck_rewrite,
    precheck_scope_inflation,
    validate_rewrite,
)
from tests.rewrite_cases import BASE_SOURCE_LINE, CASES, ValidatorCase  # noqa: E402


def _evidence_for(case: ValidatorCase) -> Evidence:
    base: dict[str, object] = dict(
        id="e1",
        source_line=BASE_SOURCE_LINE,
        evidence_type="project",
        skills=["Python"],
        duration_months=3,
        team_size=2,
    )
    base.update(case.evidence_overrides)
    return Evidence(**base)


def _rewrite_for(case: ValidatorCase) -> Rewrite:
    return Rewrite(
        requirement_id="r1",
        evidence_id="e1",
        suggested_phrasing=case.suggested_phrasing,
        facts_used=["e1"],
    )


def deterministic_predicts_reject(case: ValidatorCase) -> bool:
    """True if either free layer — scope gate or regex pre-check — rejects
    `case`, with no LLM call anywhere in this function."""
    evidence = [_evidence_for(case)]
    rewrite = _rewrite_for(case)
    if precheck_scope_inflation(rewrite, evidence) is not None:
        return True
    return precheck_rewrite(rewrite, evidence) is not None


def live_predicts_reject(case: ValidatorCase) -> bool:
    """True if the *full* three-layer `validate_rewrite` — including a real
    network call to `_call_llm_validator` — rejects `case`. Only ever invoked
    when `--live` is passed and `ANTHROPIC_API_KEY` is set."""
    evidence = [_evidence_for(case)]
    rewrite = _rewrite_for(case)
    return not validate_rewrite(rewrite, evidence).ok


def confusion(
    cases: list[ValidatorCase], predict_reject: Callable[[ValidatorCase], bool]
) -> tuple[int, int, int, int]:
    """(TP, FP, FN, TN) where "positive" means should_reject=True."""
    tp = fp = fn = tn = 0
    for case in cases:
        predicted = predict_reject(case)
        actual = case.should_reject
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def _safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else math.nan


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = (
        _safe_div(2 * precision * recall, precision + recall)
        if not (math.isnan(precision) or math.isnan(recall))
        else math.nan
    )
    return precision, recall, f1


def _fmt(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value:.3f}"


def print_markdown_table(title: str, tp: int, fp: int, fn: int, tn: int) -> None:
    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    print(f"#### {title}")
    print()
    print("| Metric | Value |")
    print("|---|---|")
    print(f"| True Positives (TP) | {tp} |")
    print(f"| False Positives (FP) | {fp} |")
    print(f"| False Negatives (FN) | {fn} |")
    print(f"| True Negatives (TN) | {tn} |")
    print(f"| Precision | {_fmt(precision)} |")
    print(f"| Recall | {_fmt(recall)} |")
    print(f"| F1 | {_fmt(f1)} |")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Additionally run the real LLM layer (_call_llm_validator) over all 30 "
            "cases. Requires ANTHROPIC_API_KEY; skipped with a message if unset."
        ),
    )
    args = parser.parse_args()

    print("=" * 78)
    print("F5 rewrite validator — precision/recall")
    print("=" * 78)
    print()
    print(
        "IMPORTANT: the table below measures the two DETERMINISTIC layers only —\n"
        "precheck_scope_inflation and precheck_rewrite. No LLM is called to produce\n"
        "it, no ANTHROPIC_API_KEY is read, and no network request is made. A case\n"
        "labelled caught_by=\"llm\" in tests/rewrite_cases.py is *expected* to show up\n"
        "as a false negative here — the whole reason engine/rewrite/validate.py has a\n"
        "third layer is that these two cannot see that class of failure. This table\n"
        "reports what the free layers alone catch, honestly, not what the full system\n"
        "catches with a mocked or live LLM standing in behind them."
    )
    print()

    tp, fp, fn, tn = confusion(CASES, deterministic_predicts_reject)
    print_markdown_table(
        "Deterministic layers only (precheck_scope_inflation + precheck_rewrite)",
        tp,
        fp,
        fn,
        tn,
    )

    llm_required = [c for c in CASES if c.caught_by == "llm"]
    print(
        f"Cases that require the semantic (LLM) layer: {len(llm_required)} / {len(CASES)} "
        f"total — these are exactly this run's false negatives:"
    )
    for case in llm_required:
        print(f"  - {case.id} ({case.category})")
    print()

    if args.live:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "--live was passed but ANTHROPIC_API_KEY is not set in the environment; "
                "skipping the live LLM run. No network call was made."
            )
        else:
            print("Running the full three-layer validator live (real LLM calls)...")
            print()
            live_tp, live_fp, live_fn, live_tn = confusion(CASES, live_predicts_reject)
            print_markdown_table(
                "Full system, live (scope gate + pre-check + real _call_llm_validator)",
                live_tp,
                live_fp,
                live_fn,
                live_tn,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
