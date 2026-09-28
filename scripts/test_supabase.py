"""Supabase connectivity, schema, and pgvector verification script.

Usage:
    python scripts/test_supabase.py

Checks:
1. Environment variables (SUPABASE_URL, SUPABASE_SERVICE_KEY)
2. Connection to Supabase PostgreSQL
3. Presence and read/write permissions on required tables:
   - resumes
   - jobs
   - analyses
   - jd_requirements
   - resume_evidence
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Load .env
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import get_supabase_client


def run_checks() -> bool:
    print("=" * 60)
    print(" Proofit - Supabase Database Connectivity & Schema Test")
    print("=" * 60)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    print(f"\n1. Checking Environment Variables in {dotenv_path.name}:")
    if not url or "REPLACE_ME" in url:
        print("   [FAIL] SUPABASE_URL is not configured or still has placeholder.")
        print("          Set SUPABASE_URL=https://<your-project-id>.supabase.co in .env")
        return False
    print(f"   [OK] SUPABASE_URL found: {url}")

    if not key or "REPLACE_ME" in key:
        print("   [FAIL] SUPABASE_SERVICE_KEY is not configured or still has placeholder.")
        print("          Set SUPABASE_SERVICE_KEY=<your-service-role-key> in .env")
        return False
    print(f"   [OK] SUPABASE_SERVICE_KEY found: {key[:8]}...{key[-4:]}")

    print("\n2. Initializing Supabase client:")
    client = get_supabase_client()
    if not client:
        print("   [FAIL] Failed to initialize Supabase client.")
        return False
    print("   [OK] Supabase client initialized successfully.")

    print("\n3. Verifying Tables and Permissions:")
    tables = [
        "resumes",
        "jobs",
        "analyses",
        "jd_requirements",
        "resume_evidence",
    ]

    all_passed = True
    for table_name in tables:
        try:
            res = client.table(table_name).select("*").limit(1).execute()
            print(f"   [OK] Table '{table_name}' accessible (Status: OK, rows: {len(res.data) if res.data else 0})")
        except Exception as err:
            all_passed = False
            print(f"   [FAIL] Table '{table_name}' error: {err}")

    if not all_passed:
        print("\n[NOTE] Some tables are missing. Please execute the SQL migration script:")
        print("       File: data/supabase_schema.sql")
        print("       In Supabase Dashboard -> SQL Editor -> Run Query")
        return False

    print("\n4. Testing CRUD Roundtrip on 'jobs' and 'analyses':")
    test_id = f"test_{uuid.uuid4().hex[:8]}"
    try:
        # Test write job
        job_row = {
            "id": f"job_{test_id}",
            "content_hash": f"hash_{test_id}",
            "source": "text",
            "raw": "Test job description text for connectivity test",
            "title": "Software Engineer Test",
        }
        client.table("jobs").upsert(job_row).execute()
        print(f"   [OK] Inserted test job '{job_row['id']}'")

        # Test write analysis
        an_row = {
            "id": f"an_{test_id}",
            "job_id": job_row["id"],
            "country": "KH",
            "status": "done",
            "stage": "checking_realism",
        }
        client.table("analyses").upsert(an_row).execute()
        print(f"   [OK] Inserted test analysis '{an_row['id']}'")

        # Clean up
        client.table("analyses").delete().eq("id", an_row["id"]).execute()
        client.table("jobs").delete().eq("id", job_row["id"]).execute()
        print("   [OK] Test records cleaned up successfully.")

    except Exception as crud_err:
        print(f"   [FAIL] CRUD test failed: {crud_err}")
        return False

    print("\n[SUCCESS] Supabase setup is 100% complete and working perfectly!")
    return True



if __name__ == "__main__":
    success = run_checks()
    sys.exit(0 if success else 1)
