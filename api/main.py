"""FastAPI entrypoint. Run with `uvicorn api.main:app --reload --port 8000`.

No CORS configuration: `web/next.config.ts` rewrites `/api/*` to this service
server-side, so the browser only ever talks to its own origin
(PERSON_B_PLAN_v2.md §8.3).
"""

from __future__ import annotations

from fastapi import FastAPI

from api.config import settings
from api.routes import analyses, health, jobs, resumes

app = FastAPI(title="Proofit API", version=settings.app_version)

app.include_router(health.router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(analyses.router, prefix="/api")
