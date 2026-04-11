"""
Supabase JWT verification as a FastAPI dependency.

Uses the JWKS endpoint (RS256 asymmetric verification) — no JWT secret needed.
Supabase publishes its public keys at:
    <SUPABASE_URL>/auth/v1/.well-known/jwks.json

The JWKS response is cached for 10 minutes to avoid hammering the endpoint on
every request while still supporting key rotation.

Usage in a protected route:

    from api.auth import get_current_user
    from fastapi import Depends

    @router.post("/some-route")
    def route(user: dict = Depends(get_current_user)):
        user_id = user["sub"]  # Supabase user UUID

The JWT is expected in the Authorization header as:
    Authorization: Bearer <supabase_jwt>
"""

import time

import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from api.config import settings

_bearer = HTTPBearer()

# ── JWKS cache ────────────────────────────────────────────────────────────────
_JWKS_TTL = 600  # seconds (10 min — Supabase rotates keys infrequently)
_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0


def _get_jwks() -> dict:
    """Return the cached JWKS, refreshing if older than _JWKS_TTL seconds."""
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or (time.monotonic() - _jwks_fetched_at) > _JWKS_TTL:
        url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = time.monotonic()
    return _jwks_cache


# ── Dependency ────────────────────────────────────────────────────────────────


def verify_token(token: str) -> dict:
    """
    Verify a raw Supabase JWT string against the project's JWKS public keys.
    Returns the decoded payload on success. Raises HTTP 401 on failure.

    Used directly by routes that receive the token as a query param
    (e.g. browser-initiated OAuth redirects where a Bearer header is not possible).
    """
    try:
        jwks = _get_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
        )
    except (JWTError, requests.RequestException) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Verify the Supabase JWT from the Authorization: Bearer header.
    Thin wrapper around verify_token for use as a FastAPI Depends.
    """
    return verify_token(credentials.credentials)
