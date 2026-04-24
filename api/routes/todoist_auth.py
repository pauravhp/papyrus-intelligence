"""
GET /auth/todoist          — start Todoist OAuth; browser-initiated, accepts ?token=<jwt>
GET /auth/todoist/callback — receive auth code, store access token, redirect to frontend

Flow:
  1. Frontend navigates browser to /auth/todoist?token=<supabase_jwt>
  2. Backend validates JWT, signs user_id + timestamp into HMAC state param
  3. Browser redirected to Todoist consent screen (scope: data:read_write)
  4. Todoist redirects back to /auth/todoist/callback?code=...&state=...
  5. Backend verifies state HMAC, exchanges code for access token, stores in Supabase
  6. Browser redirected to http://localhost:3000/onboard

State param format: "<user_id>:<unix_timestamp>:<hmac_sha256_hex>"
No PKCE — Todoist OAuth 2.0 does not support code_verifier.
Todoist access tokens are indefinite — no refresh_token issued.
"""

import hashlib
import hmac
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from api.auth import verify_token
from api.config import settings
from api.db import supabase

router = APIRouter()

_REDIRECT_URI = "http://localhost:8000/auth/todoist/callback"
_STATE_MAX_AGE = 600  # 10 minutes


def _sign_state(user_id: str) -> str:
    """Return '<user_id>:<timestamp>:<hmac>' — carries user identity through redirect."""
    timestamp = str(int(time.time()))
    payload = f"{user_id}:{timestamp}"
    sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> str:
    """Verify HMAC + expiry; return user_id on success, raise ValueError on failure."""
    parts = state.split(":")
    if len(parts) != 3:
        raise ValueError("malformed state")
    user_id, timestamp_str, received_sig = parts
    payload = f"{user_id}:{timestamp_str}"
    expected_sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(received_sig, expected_sig):
        raise ValueError("state signature mismatch")
    if int(time.time()) - int(timestamp_str) > _STATE_MAX_AGE:
        raise ValueError("state expired — restart OAuth flow")
    return user_id


@router.get("/auth/todoist")
def todoist_oauth_start(
    token: str = Query(..., description="Supabase access token from the frontend session"),
    redirect_after: str = Query(default=None, description="Frontend URL to redirect to after OAuth completes"),
) -> RedirectResponse:
    """
    Browser-initiated Todoist OAuth entry point.

    Validates the Supabase JWT, generates an HMAC-signed state, and redirects
    to Todoist's consent screen. No PKCE — Todoist does not support code_verifier.
    """
    user = verify_token(token)
    user_id: str = user["sub"]

    # Store redirect_after so the callback can use it
    supabase.from_("users").update(
        {"oauth_redirect_after": redirect_after}
    ).eq("id", user_id).execute()

    auth_url = (
        "https://api.todoist.com/oauth/authorize"
        f"?client_id={settings.TODOIST_CLIENT_ID}"
        "&scope=data:read_write"
        f"&state={_sign_state(user_id)}"
    )
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/todoist/callback")
def todoist_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """
    Todoist redirects here after user grants consent.

    Verifies HMAC state, exchanges code for access token via Todoist token endpoint,
    and stores {"access_token": "...", "granted_at": "<ISO>"} in users.todoist_oauth_token.
    """
    try:
        user_id = _verify_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Read stored redirect_after
    row = (
        supabase.from_("users")
        .select("oauth_redirect_after")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    stored_redirect = (row.data or {}).get("oauth_redirect_after")
    if stored_redirect and stored_redirect.startswith("/"):
        redirect_after = f"{settings.FRONTEND_URL}{stored_redirect}"
    else:
        redirect_after = stored_redirect or f"{settings.FRONTEND_URL}/onboard"

    # Exchange authorization code for access token
    resp = requests.post(
        "https://api.todoist.com/oauth/access_token",
        data={
            "client_id": settings.TODOIST_CLIENT_ID,
            "client_secret": settings.TODOIST_CLIENT_SECRET,
            "code": code,
            "redirect_uri": _REDIRECT_URI,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Todoist token exchange failed: {resp.text}",
        )

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Todoist did not return an access_token",
        )

    supabase.from_("users").update({
        "todoist_oauth_token": {
            "access_token": access_token,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        },
        "oauth_redirect_after": None,
    }).eq("id", user_id).execute()

    return RedirectResponse(url=redirect_after, status_code=302)
