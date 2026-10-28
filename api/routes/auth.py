"""Authentication endpoints (`GET /api/auth/me`, Phase 1.3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import CurrentUser, get_current_user

router = APIRouter()


@router.get("/auth/me")
async def get_me(user: CurrentUser = Depends(get_current_user)) -> dict:  # noqa: B008
    return {"id": user.id, "email": user.email}

