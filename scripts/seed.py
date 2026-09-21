"""Database seed script for Proofit (Supabase + pgvector).

Populates Supabase database tables (`jobs`, `resumes`, `analyses`, `jd_requirements`, `resume_evidence`)
from golden fixtures in `data/fixtures/`.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_supabase_client
from engine.gemini_client import get_embedding
from engine.normalize.schema import Job, Match, Resume

logger = logging.getLogger(__name__)

FIXTURE_NAMES = ("fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic")


def seed_database() -> None:
    """Seed Supabase database with all golden fixtures and embeddings."""
    print("=" * 60)
    print(" Proofit - Seeding Database (Supabase + pgvector)")
    print("=" * 60)

    client = get_supabase_client()
    fixtures_dir = Path(__file__).resolve().parents[1] / "data" / "fixtures"

    if not client:
        print("\n[Offline Mode] Supabase credentials not set or placeholder detected.")
        print("Verifying fixtures and schemas locally...")
        for name in FIXTURE_NAMES:
            p = fixtures_dir / f"{name}.json"
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                job = Job.model_validate(data["job"])
                resume = Resume.model_validate(data["resume"])
                match = Match.model_validate(data)
                print(f"  [OK] Verified fixture: {name} (Job: '{job.title}', Match score: {match.coverage_score}%)")
        print("\nSet SUPABASE_URL and SUPABASE_SERVICE_KEY in .env to write to Supabase.")
        return

    print("\nConnected to Supabase. Seeding golden fixtures...")

    for name in FIXTURE_NAMES:
        fixture_file = fixtures_dir / f"{name}.json"
        if not fixture_file.exists():
            print(f"  [SKIP] Skipping {name}: file not found.")
            continue

        data = json.loads(fixture_file.read_text(encoding="utf-8"))
        job = Job.model_validate(data["job"])
        resume = Resume.model_validate(data["resume"])
        match = Match.model_validate(data)

        job_id = f"job_{name}"
        resume_id = f"res_{name}"
        analysis_id = f"an_{name}"

        # 1. Upsert Resume
        res_row = {
            "id": resume_id,
            "filename": f"{name}_resume.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10240,
            "raw_text": resume.candidate_summary,
            "normalized": resume.model_dump(mode="json"),
        }
        client.table("resumes").upsert(res_row).execute()

        # 2. Upsert Job
        job_row = {
            "id": job_id,
            "content_hash": job.content_hash,
            "source": job.source_type or "text",
            "raw": f"Job Title: {job.title}\nCompany: {job.company or ''}\n\nRequirements:\n" + "\n".join(f"- {r.text}" for r in job.requirements),
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "normalized": job.model_dump(mode="json"),
        }
        client.table("jobs").upsert(job_row).execute()

        # 3. Upsert Analysis
        an_row = {
            "id": analysis_id,
            "resume_id": resume_id,
            "job_id": job_id,
            "country": "KH",
            "status": "done",
            "stage": "checking_realism",
            "match": match.model_dump(mode="json"),
        }
        client.table("analyses").upsert(an_row).execute()

        # 4. Generate & Upsert Embeddings (pgvector)
        print(f"  Generating embeddings for {name} ({len(job.requirements)} reqs, {len(resume.evidence)} evidence)...")
        try:
            req_vectors = {req.id: get_embedding(req.text) for req in job.requirements}
            req_rows = [
                {
                    "jd_id": job_id,
                    "jd_hash": job.content_hash,
                    "req_id": req.id,
                    "category": req.category,
                    "is_required": (req.priority == "required"),
                    "description": req.text,
                    "canonical_skill": req.normalized_skill,
                    "embedding": req_vectors[req.id],
                }
                for req in job.requirements
            ]
            client.table("jd_requirements").upsert(req_rows).execute()

            ev_vectors = {ev.id: get_embedding(ev.source_line) for ev in resume.evidence}
            ev_rows = [
                {
                    "resume_id": resume_id,
                    "evidence_id": ev.id,
                    "evidence_type": ev.evidence_type,
                    "description": ev.source_line,
                    "duration_months": ev.duration_months or 0,
                    "team_size": ev.team_size,
                    "outcome": ev.outcome,
                    "embedding": ev_vectors[ev.id],
                }
                for ev in resume.evidence
            ]
            client.table("resume_evidence").upsert(ev_rows).execute()
        except Exception as emb_err:
            print(f"  [NOTE] Vector embedding insertion note for {name}: {emb_err}")

        print(f"  [OK] Seeded fixture '{name}' -> Analysis ID: {analysis_id}")

    print("\n[SUCCESS] Database seeding finished successfully!")


if __name__ == "__main__":
    seed_database()

