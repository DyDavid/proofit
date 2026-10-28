"""Supabase JWT verification and guest IP hashing for FastAPI routes (Phase 1).

Supports both asymmetric JWKS (`ES256`, `RS256` via `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`)
and legacy `HS256` (`SUPABASE_JWT_SECRET`), with fallback to `supabase.auth.get_user(token)`.
"""

from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache

import anyio
import jwt
from fastapi import Header, Request
from jwt import PyJWKClient
from pydantic import BaseModel

from api.config import settings
from api.db import get_supabase_client
from api.errors import ApiError

logger = logging.getLogger(__name__)


class CurrentUser(BaseModel):
    id: str
    email: str | None = None


@lru_cache(maxsize=4)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def _decode_with_jwks(token: str, supabase_url: str) -> dict:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    jwk_client = _get_jwks_client(jwks_url)
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
    )


def _decode_with_hs256(token: str, secret: str) -> dict:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="authenticated",
    )


async def verify_bearer_token(token: str) -> CurrentUser:
    """Verify a Supabase JWT and return `{id, email}` or raise 401 ApiError."""
    if not token:
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing authentication token.",
        )

    jwt_secret = settings.supabase_jwt_secret or os.getenv("SUPABASE_JWT_SECRET")
    supabase_url = settings.supabase_url or os.getenv("SUPABASE_URL")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as err:
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Invalid authentication token.",
        ) from err

    alg = header.get("alg", "")

    # 1. Legacy HS256 secret verification
    if alg == "HS256" and jwt_secret:
        try:
            payload = _decode_with_hs256(token, jwt_secret)
            sub = payload.get("sub")
            if not sub:
                raise ValueError("Token missing sub claim")
            return CurrentUser(id=str(sub), email=payload.get("email"))
        except Exception as err:
            raise ApiError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            ) from err

    # 2. Asymmetric JWKS verification (ES256 / RS256)
    if alg in ("ES256", "RS256") and supabase_url:
        try:
            payload = await anyio.to_thread.run_sync(_decode_with_jwks, token, supabase_url)
            sub = payload.get("sub")
            if not sub:
                raise ValueError("Token missing sub claim")
            return CurrentUser(id=str(sub), email=payload.get("email"))
        except Exception as err:
            raise ApiError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            ) from err

    # 3. Fallback to Supabase Auth API `auth.get_user(token)` if client is available
    client = get_supabase_client()
    if client is not None:
        try:
            res = await anyio.to_thread.run_sync(client.auth.get_user, token)
            user = getattr(res, "user", None)
            if user and getattr(user, "id", None):
                return CurrentUser(id=str(user.id), email=getattr(user, "email", None))
        except Exception as err:
            logger.debug("Supabase auth.get_user failed: %s", err)

    raise ApiError(
        status_code=401,
        code="UNAUTHORIZED",
        message="Invalid or expired authentication token.",
    )


async def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """FastAPI dependency that requires a valid Bearer token (raises 401 otherwise)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Authentication required.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    return await verify_bearer_token(token)


async def get_optional_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser | None:
    """FastAPI dependency that returns `CurrentUser` if a Bearer token is sent,
    `None` when no Authorization header is present, and raises 401 if a Bearer
    token is sent but is invalid or expired.
    """
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Invalid Authorization header format.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    return await verify_bearer_token(token)


def get_client_ip(request: Request) -> str:
    """Extract client IP behind Render/Railway proxy (`X-Forwarded-For` first entry)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def hash_guest_ip(request: Request) -> str:
    """Return a salted SHA-256 hash of the client IP (never store raw IPs)."""
    ip = get_client_ip(request)
    salt = settings.guest_ip_salt or os.getenv("GUEST_IP_SALT") or "proofit-default-guest-salt"
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()

