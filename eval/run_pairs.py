"""Runs 20 evaluation resume-JD pairs through live engine and baseline matcher.

Outputs JSON results to eval/system_outputs.json for Kappa agreement analysis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.match import run_baseline, run_match
from engine.normalize import normalize_jd, normalize_resume
from engine.normalize.schema import SCHEMA_VERSION

PAIRS_FILE = ROOT_DIR / "eval" / "pairs.json"
OUTPUT_FILE = ROOT_DIR / "eval" / "system_outputs.json"


def run_evaluation_suite() -> None:
    print(f"Starting Evaluation Run [Schema Version: {SCHEMA_VERSION}]")

    # Load 20 evaluation pairs if available, or generate from data/jds and data/resumes
    pairs = []
    if PAIRS_FILE.is_file():
        pairs = json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
    else:
        # Fall back to available data fixtures/files
        jds_dir = ROOT_DIR / "data" / "jds"
        resumes_dir = ROOT_DIR / "data" / "resumes"

        jd_files = list(jds_dir.glob("*.txt")) if jds_dir.is_dir() else []
        resume_files = list(resumes_dir.glob("*.pdf")) if resumes_dir.is_dir() else []

        if jd_files and resume_files:
            for j_path in jd_files[:4]:
                for r_path in resume_files[:5]:
                    pairs.append({
                        "pair_id": f"pair_{len(pairs)+1}",
                        "jd_path": str(j_path),
                        "resume_path": str(r_path),
                    })

    if not pairs:
        print("No evaluation pairs found in eval/pairs.json or data/! Creating stub output.")
        results = {"engine_version": SCHEMA_VERSION, "total_pairs": 0, "evaluations": []}
        OUTPUT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
        return

    outputs = []
    for pair in pairs:
        print(f"Evaluating pair: {pair.get('pair_id')} ...")

        # Load JD and Resume
        jd_text = Path(pair["jd_path"]).read_text(encoding="utf-8")
        res_bytes = Path(pair["resume_path"]).read_bytes()

        job = normalize_jd(jd_text)
        resume = normalize_resume(res_bytes, Path(pair["resume_path"]).name)

        match_res = run_match(job, resume)
        base_res = run_baseline(job, resume)

        outputs.append({
            "pair_id": pair.get("pair_id"),
            "job_title": job.title,
            "coverage_score": match_res.coverage_score,
            "realism_verdict": match_res.realism_verdict,
            "system_match": match_res.model_dump(mode="json"),
            "baseline_match": base_res.model_dump(mode="json"),
        })

    final_payload = {
        "engine_version": SCHEMA_VERSION,
        "total_pairs": len(outputs),
        "evaluations": outputs,
    }

    OUTPUT_FILE.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")
    print(f"Successfully exported outputs to {OUTPUT_FILE}")


if __name__ == "__main__":
    run_evaluation_suite()
