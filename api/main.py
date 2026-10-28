"""FastAPI entrypoint. Run with `uvicorn api.main:app --reload --port 8000`.

No CORS configuration: `web/next.config.ts` rewrites `/api/*` to this service
server-side, so the browser only ever talks to its own origin
(PERSON_B_PLAN_v2.md §8.3).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

# Always reload .env so that modifications to keys take effect immediately
env_file = find_dotenv(usecwd=True) or Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_file, override=True)


from api.billing.router import router as billing_router
from api.config import settings
from api.errors import install_error_handlers
from api.routes import analyses, auth, countries, health, jobs, resumes

app = FastAPI(title="Proofit API", version=settings.app_version)
install_error_handlers(app)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(resumes.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(analyses.router, prefix="/api")
app.include_router(countries.router, prefix="/api")
