"""Supabase JWT verification and guest IP hashing for FastAPI routes (Phase 1).

Supports both asymmetric JWKS (`ES256`, `RS256` via `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`)
and legacy `HS256` (`SUPABASE_JWT_SECRET`), with fallback to `supabase.auth.get_user(token)`.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from functools import lru_cache

import anyio
import httpx
import jwt
from fastapi import Header, Request
from jwt import PyJWKClient
from pydantic import BaseModel

from api.admission import admit_request
from api.config import is_admin_email, settings
from api.db import validate_persistence_config
from api.errors import ApiError
from engine.execution import BoundedWorkPool, WorkCapacityError, WorkTimeoutError

logger = logging.getLogger(__name__)

_known_user_emails: OrderedDict[str, str] = OrderedDict()
_email_lock = threading.Lock()
_auth_pool = BoundedWorkPool("authentication")


def register_user_email(user_id: str, email: str | None) -> None:
    if email:
        with _email_lock:
            _known_user_emails[user_id] = email.strip().lower()
            _known_user_emails.move_to_end(user_id)
            while len(_known_user_emails) > 5000:
                _known_user_emails.popitem(last=False)


def get_user_email(user_id: str) -> str | None:
    with _email_lock:
        return _known_user_emails.get(user_id)


class CurrentUser(BaseModel):
    id: str
    email: str | None = None

    @property
    def is_admin(self) -> bool:
        return is_admin_email(self.email)


class RefreshLimitedJWKClient(PyJWKClient):
    """Cooldown applies to failed fetches too, including older supported PyJWT versions."""

    def __init__(self, url):
        super().__init__(url, cache_keys=False, lifespan=settings.auth_jwks_refresh_seconds,
                         timeout=settings.auth_provider_timeout_seconds)
        self._refresh_lock = threading.RLock()
        self._attempt_at = None
        self._last_data = None

    def get_signing_key(self, kid):
        # Own the refresh policy rather than stacking SDK-specific cooldowns.
        with self._refresh_lock:
            keys = self.get_signing_keys()
            key = self.match_kid(keys, kid)
            if key is None:
                key = self.match_kid(self.get_signing_keys(refresh=True), kid)
            if key is None:
                raise jwt.PyJWKClientError("Unknown authentication signing key")
            return key

    def fetch_data(self):
        with self._refresh_lock:
            now = time.monotonic()
            if self._attempt_at is not None and now - self._attempt_at < settings.auth_jwks_refresh_seconds:
                if self._last_data is None:
                    raise jwt.PyJWKClientConnectionError("Authentication keys temporarily unavailable")
                return self._last_data
            self._attempt_at = now
            try:
                data = super().fetch_data()
                if not isinstance(data, dict) or not isinstance(data.get("keys"), list) or len(data["keys"]) > 32:
                    raise jwt.PyJWKClientConnectionError("Invalid authentication key set")
                self._last_data = data
                return data
            except Exception:
                self._last_data = None
                raise jwt.PyJWKClientConnectionError("Authentication keys unavailable") from None


@lru_cache(maxsize=4)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    return RefreshLimitedJWKClient(jwks_url)


def _decode_with_jwks(token: str, supabase_url: str) -> dict:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    jwk_client = _get_jwks_client(jwks_url)
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        options={"require": ["exp", "sub"]},
    )


def _decode_with_hs256(token: str, secret: str) -> dict:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience="authenticated",
        options={"require": ["exp", "sub"]},
    )


async def verify_bearer_token(token: str, subject: str = "direct") -> CurrentUser:
    """Verify a Supabase JWT and return `{id, email}` or raise 401 ApiError."""
    if not token or len(token) > 8192 or token.count(".") != 2 or not all(token.split(".")):
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Missing authentication token.",
        )

    jwt_secret = settings.supabase_jwt_secret or os.getenv("SUPABASE_JWT_SECRET")
    supabase_url = settings.supabase_url or os.getenv("SUPABASE_URL")

    try:
        header = jwt.get_unverified_header(token)
        payload = jwt.decode(token, options={"verify_signature": False})
        expiry = payload.get("exp")
        if (not isinstance(payload.get("sub"), str) or not 0 < len(payload["sub"]) <= 255
                or type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time()):
            raise ValueError("Invalid token claims")
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError) as err:
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Invalid authentication token.",
        ) from err

    alg = header.get("alg", "")
    if alg not in ("HS256", "ES256", "RS256") or len(str(header.get("kid", ""))) > 128:
        raise ApiError(401, "UNAUTHORIZED", "Invalid authentication token.")

    try:
        return await anyio.to_thread.run_sync(lambda: _auth_pool.run(
            lambda: _verify_token_sync(token, alg, jwt_secret, supabase_url, subject),
            timeout=settings.auth_timeout_seconds, limit=settings.max_concurrent_auth,
        ))
    except WorkCapacityError:
        raise ApiError(429, "RATE_LIMITED", "Authentication is busy. Please try again shortly.") from None
    except WorkTimeoutError:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Authentication temporarily unavailable.") from None


def _verify_token_sync(token, alg, jwt_secret, supabase_url, subject):
    admit_request("auth", subject, settings.auth_requests_per_min, settings.auth_global_requests_per_min)

    # 1. Legacy HS256 secret verification
    if alg == "HS256" and jwt_secret:
        try:
            payload = _decode_with_hs256(token, jwt_secret)
            sub = payload.get("sub")
            if not sub:
                raise ValueError("Token missing sub claim")
            user = CurrentUser(id=str(sub), email=payload.get("email"))
            register_user_email(user.id, user.email)
            return user
        except Exception as err:
            raise ApiError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            ) from err

    # 2. Asymmetric JWKS verification (ES256 / RS256)
    if alg in ("ES256", "RS256") and supabase_url:
        try:
            payload = _decode_with_jwks(token, supabase_url)
            sub = payload.get("sub")
            if not sub:
                raise ValueError("Token missing sub claim")
            user = CurrentUser(id=str(sub), email=payload.get("email"))
            register_user_email(user.id, user.email)
            return user
        except jwt.PyJWKClientConnectionError:
            raise ApiError(503, "SERVICE_UNAVAILABLE", "Authentication temporarily unavailable.") from None
        except Exception as err:
            raise ApiError(
                status_code=401,
                code="UNAUTHORIZED",
                message="Invalid or expired authentication token.",
            ) from err

    # 3. Fallback to Supabase Auth API `auth.get_user(token)` if client is available
    config = validate_persistence_config()
    if config is not None:
        try:
            url, key = config
            with httpx.Client(timeout=settings.auth_provider_timeout_seconds, follow_redirects=False, trust_env=False) as client:
                response = client.get(url.rstrip("/") + "/auth/v1/user", headers={"apikey": key, "Authorization": "Bearer " + token})
            if response.status_code >= 500 or response.status_code == 429:
                raise ApiError(503, "SERVICE_UNAVAILABLE", "Authentication temporarily unavailable.")
            user_data = response.json() if response.status_code == 200 else {}
            if user_data.get("id"):
                user = CurrentUser(id=str(user_data["id"]), email=user_data.get("email"))
                register_user_email(user.id, user.email)
                return user
        except ApiError:
            raise
        except Exception:
            raise ApiError(503, "SERVICE_UNAVAILABLE", "Authentication temporarily unavailable.") from None

    raise ApiError(
        status_code=401,
        code="UNAUTHORIZED",
        message="Invalid or expired authentication token.",
    )


async def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> CurrentUser:
    """FastAPI dependency that requires a valid Bearer token (raises 401 otherwise)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Authentication required.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    return await verify_bearer_token(token, hash_guest_ip(request))


async def get_optional_user(
    request: Request,
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
    return await verify_bearer_token(token, hash_guest_ip(request))


def _parse_ip(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Validate and return an IP address object, or None if malformed."""
    cleaned = ip_str.strip()
    if not cleaned:
        return None
    try:
        return ipaddress.ip_address(cleaned)
    except ValueError:
        return None


@lru_cache(maxsize=16)
def _parse_trusted_proxy_networks(
    raw_proxies: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse a comma-separated string of IPs/CIDRs into network objects."""
    if not raw_proxies or not raw_proxies.strip():
        return ()
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw_proxies.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            networks.append(ipaddress.ip_network(cleaned, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid trusted_proxies entry in configuration.")
    return tuple(networks)


def _get_trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Return configured trusted proxy networks from settings or environment."""
    raw = settings.trusted_proxies or os.getenv("TRUSTED_PROXIES", "")
    return _parse_trusted_proxy_networks(raw)


def _is_ip_trusted(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    """Return True if `ip` belongs to any configured trusted proxy network."""
    return any(ip in net for net in networks)


def get_client_ip(request: Request) -> str:
    """Extract validated client IP, trusting forwarding headers only from trusted proxies.

    Security invariants:
    - If the connection peer (`request.client.host`) is not in `TRUSTED_PROXIES`,
      all forwarding headers (`X-Forwarded-For`) are ignored and the peer IP is used.
    - When the connection peer is a trusted proxy, `X-Forwarded-For` is traversed
      from right to left (closest hop to furthest). The first valid IP address not in
      `TRUSTED_PROXIES` is returned as the client IP.
    - If the header is missing, empty, or contains a malformed IP at any inspected
      trusted hop, the function falls back to the connection peer IP.
    """
    raw_peer = request.client.host if (request.client and request.client.host) else None
    if not raw_peer:
        return "127.0.0.1"

    if raw_peer == "testclient":
        peer_ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address("127.0.0.1")
    else:
        parsed_peer = _parse_ip(raw_peer)
        if parsed_peer is None:
            return "127.0.0.1"
        peer_ip = parsed_peer

    trusted_networks = _get_trusted_proxy_networks()
    if not trusted_networks or not _is_ip_trusted(peer_ip, trusted_networks):
        return str(peer_ip)

    forwarded_headers = request.headers.getlist("x-forwarded-for") if hasattr(request.headers, "getlist") else []
    if not forwarded_headers:
        single = request.headers.get("x-forwarded-for")
        if single is not None:
            forwarded_headers = [single]

    combined = ",".join(forwarded_headers)
    if not combined.strip():
        return str(peer_ip)

    raw_parts = [part.strip() for part in combined.split(",")]
    if not raw_parts:
        return str(peer_ip)

    # Traverse right-to-left (from the hop closest to our server back toward the client).
    for entry in reversed(raw_parts):
        entry_ip = _parse_ip(entry)
        if entry_ip is None:
            # Malformed hop in the trusted chain -> untrusted forwarding info, use peer.
            return str(peer_ip)
        if not _is_ip_trusted(entry_ip, trusted_networks):
            return str(entry_ip)

    # All hops in X-Forwarded-For are trusted proxies; return the leftmost valid hop.
    leftmost_ip = _parse_ip(raw_parts[0])
    return str(leftmost_ip) if leftmost_ip is not None else str(peer_ip)


def hash_guest_ip(request: Request) -> str:
    """Return a salted SHA-256 hash of the client IP (never store or log raw IPs)."""
    ip = get_client_ip(request)
    salt = settings.guest_ip_salt or os.getenv("GUEST_IP_SALT") or "proofit-default-guest-salt"
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()

