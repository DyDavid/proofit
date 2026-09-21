"""Computes Agreement Metrics (Percent Agreement & Cohen's Kappa) for Evaluation Chapter.

Usage: python eval/analysis.py
"""

from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
SYSTEM_OUTPUT_FILE = EVAL_DIR / "system_outputs.json"


def cohen_kappa_3class(rater1: list[str], rater2: list[str]) -> float:
    """Calculates Cohen's Kappa for 3-class verdicts ('proven', 'partial', 'missing')."""
    if len(rater1) != len(rater2) or len(rater1) == 0:
        return 0.0

    n = len(rater1)
    categories = ["proven", "partial", "missing"]
    cat_to_idx = {c: i for i, c in enumerate(categories)}

    # Build confusion matrix
    matrix = [[0] * 3 for _ in range(3)]
    po_count = 0
    for r1, r2 in zip(rater1, rater2):
        if r1 in cat_to_idx and r2 in cat_to_idx:
            i, j = cat_to_idx[r1], cat_to_idx[r2]
            matrix[i][j] += 1
            if r1 == r2:
                po_count += 1

    po = po_count / n

    # Expected agreement pe
    pe = 0.0
    for k in range(3):
        r1_sum = sum(matrix[k][j] for j in range(3))
        r2_sum = sum(matrix[i][k] for i in range(3))
        pe += (r1_sum / n) * (r2_sum / n)

    if pe == 1.0:
        return 1.0

    return (po - pe) / (1.0 - pe)


def run_agreement_analysis() -> None:
    print("=== Spean Evaluation Study Analysis ===")

    if not SYSTEM_OUTPUT_FILE.is_file():
        print(f"File {SYSTEM_OUTPUT_FILE} not found. Run `python eval/run_pairs.py` first.")
        return

    data = json.loads(SYSTEM_OUTPUT_FILE.read_text(encoding="utf-8"))
    evaluations = data.get("evaluations", [])
    print(f"Loaded {len(evaluations)} pair evaluations [Engine Version: {data.get('engine_version')}].")

    if not evaluations:
        print("No evaluation records present.")
        return

    # Extract requirement-level verdicts
    sys_verdicts = []
    base_verdicts = []

    for ev in evaluations:
        sys_m = ev.get("system_match", {})
        base_m = ev.get("baseline_match", {})

        for res in sys_m.get("results", []):
            sys_verdicts.append(res.get("verdict"))

        for b_res in base_m.get("results", []):
            base_verdicts.append(b_res.get("verdict"))

    agree_count = sum(1 for s, b in zip(sys_verdicts, base_verdicts) if s == b)
    percent_agree = (agree_count / len(sys_verdicts)) * 100 if sys_verdicts else 0.0
    kappa = cohen_kappa_3class(sys_verdicts, base_verdicts)

    print("\n--- Summary Results ---")
    print(f"Total Requirements Evaluated: {len(sys_verdicts)}")
    print(f"System vs Baseline Percent Agreement: {percent_agree:.1f}%")
    print(f"System vs Baseline Cohen's Kappa (κ): {kappa:.3f}")


if __name__ == "__main__":
    run_agreement_analysis()
