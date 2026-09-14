"""`GET /api/health` — polled by `.github/workflows/keepalive.yml` (Phase 1
task 7) so the Render free-tier service rarely sleeps."""

from __future__ import annotations

from fastapi import APIRouter

from api.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "engine_mode": settings.engine_mode,
        "app_version": settings.app_version,
    }
