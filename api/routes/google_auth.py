"""
GET /auth/google          — start Google OAuth; browser-initiated, accepts ?token=<jwt>
GET /auth/google/callback — receive auth code, store credentials, redirect to frontend

Flow:
  1. Frontend navigates browser to /auth/google?token=<supabase_jwt>
  2. Backend validates JWT, signs user_id + timestamp into HMAC state param
  3. Browser redirected to Google consent screen
  4. Google redirects back to /auth/google/callback?code=...&state=...
  5. Backend verifies state HMAC, exchanges code for tokens, stores in Supabase
  6. Browser redirected to http://localhost:3000/onboard

State param format: "<user_id>:<unix_timestamp>:<hmac_sha256_hex>"
All three segments are colon-free (UUID has hyphens only; timestamp is digits;
HMAC hex is 0-9a-f), so split(":", 2) gives exactly three clean parts.
"""

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from api.auth import verify_token
from api.config import settings
from api.db import supabase

router = APIRouter()

_REDIRECT_URI = "http://localhost:8000/auth/google/callback"
_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
_STATE_MAX_AGE = 600  # seconds — consent screen should complete in <10 min


# ── Helpers ───────────────────────────────────────────────────────────────────


def _client_config() -> dict:
    """Build the OAuth2 client config dict from settings (avoids a file read)."""
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_REDIRECT_URI],
        }
    }


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


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/auth/google")
def google_oauth_start(
    token: str = Query(..., description="Supabase access token from the frontend session"),
    redirect_after: str = Query(default=None, description="Frontend URL to redirect to after OAuth completes"),
) -> RedirectResponse:
    """
    Browser-initiated OAuth entry point.

    The frontend passes the Supabase JWT as a query param because browser
    navigation does not support custom request headers. The JWT is validated
    immediately and never forwarded to Google — only a signed, opaque state
    token carrying the user_id is included in the consent URL.

    google-auth-oauthlib >= 1.2 defaults to autogenerate_code_verifier=True,
    so we generate the PKCE verifier here, store it in Supabase, and retrieve
    it in the callback — the two Flow objects cannot share state otherwise.
    """
    user = verify_token(token)
    user_id: str = user["sub"]

    flow = Flow.from_client_config(_client_config(), scopes=_SCOPES, redirect_uri=_REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",   # force refresh_token on every grant
        state=_sign_state(user_id),
    )

    # Persist code_verifier and optional redirect_after so the callback can
    # complete the PKCE exchange and redirect to the right frontend page.
    supabase.from_("users").update(
        {"oauth_code_verifier": flow.code_verifier, "oauth_redirect_after": redirect_after}
    ).eq("id", user_id).execute()

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/auth/google/callback")
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """
    Google redirects here after user grants (or denies) consent.

    Verifies the HMAC state, exchanges the auth code for an access + refresh
    token, and persists the full Credentials JSON as jsonb in users.google_credentials.
    Redirects to the frontend onboard page on success.

    Note: google_credentials is stored as plain jsonb for now.
    Encryption via pgcrypto (encrypt_field SQL function) is a pending migration —
    see LEARNINGS.md "Frontend Auth Setup" for context.
    """
    try:
        user_id = _verify_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Retrieve the PKCE code_verifier and redirect_after stored during google_oauth_start.
    row = (
        supabase.from_("users")
        .select("oauth_code_verifier, oauth_redirect_after")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if row is None or row.data is None:
        # User row doesn't exist — stale session; redirect to login
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=session_expired")

    code_verifier = (row.data or {}).get("oauth_code_verifier")
    stored_redirect = (row.data or {}).get("oauth_redirect_after")
    if stored_redirect and stored_redirect.startswith("/"):
        redirect_after = f"{settings.FRONTEND_URL}{stored_redirect}"
    else:
        redirect_after = stored_redirect or f"{settings.FRONTEND_URL}/onboard"

    flow = Flow.from_client_config(
        _client_config(),
        scopes=_SCOPES,
        redirect_uri=_REDIRECT_URI,
        code_verifier=code_verifier,
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Token exchange failed: {exc}",
        ) from exc

    # Clear the one-time verifier and redirect_after now that the exchange is complete.
    supabase.from_("users").update(
        {"oauth_code_verifier": None, "oauth_redirect_after": None}
    ).eq("id", user_id).execute()

    creds_dict = json.loads(flow.credentials.to_json())

    result = (
        supabase.from_("users")
        .update({"google_credentials": creds_dict})
        .eq("id", user_id)
        .execute()
    )
    if hasattr(result, "error") and result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Supabase write failed: {result.error}",
        )

    return RedirectResponse(url=redirect_after, status_code=302)
