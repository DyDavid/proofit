"""Seeds fixture analyses into the API store for local demo and testing.

Run with: python scripts/seed_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.store import store

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def seed_demo_data() -> list[str]:
    """Seeds the 3 golden fixtures into store.analyses."""
    seeded_ids = []
    fixtures = ["fresh_grad_strong_fit", "fresh_grad_stretch", "unrealistic"]

    for name in fixtures:
        path = FIXTURES_DIR / f"{name}.json"
        if not path.is_file():
            print(f"Skipping {name}: file not found.")
            continue

        raw = json.loads(path.read_text(encoding="utf-8"))
        match = store.pick_fixture(name)

        # Create store records
        res_rec = store.add_resume(
            filename=f"{name}_resume.pdf",
            content_type="application/pdf",
            size=1024,
            data=b"Mock Resume Bytes",
        )
        job_rec, _ = store.add_job(
            raw=match.job.title if match.job else "Sample Job",
            source="text",
        )

        an_rec = store.create_analysis(
            resume_id=res_rec.id,
            job_id=job_rec.id,
            country=match.job.country if (match.job and match.job.country) else "KH",
        )
        an_rec.status = "done"
        an_rec.match = match
        seeded_ids.append(an_rec.id)
        print(f"Seeded fixture '{name}' -> Analysis ID: {an_rec.id}")

    return seeded_ids


if __name__ == "__main__":
    print("Seeding demo fixture analyses...")
    ids = seed_demo_data()
    print(f"Done! Seeded {len(ids)} analyses.")
