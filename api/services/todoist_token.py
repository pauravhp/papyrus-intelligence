"""
Token freshness layer for Todoist. Every Todoist API call should go through
get_valid_todoist_token(supabase, user_id) instead of reading
users.todoist_oauth_token directly.

Background: Todoist apps registered after early 2025 issue 1-hour access
tokens with mandatory rotating refresh tokens. The "Papyrus (Production)" app
is one of these — without proactive refresh, every user becomes unable to
call the Todoist API past the first hour after onboarding.

Stored token blob shape (users.todoist_oauth_token):
    {
        "access_token":  "...",
        "refresh_token": "..." | None,   # may be absent for legacy long-lived
        "expires_at":    <unix_seconds>  | None,   # absent for legacy
        "token_type":    "Bearer",
    }

Legacy long-lived rows ({"access_token": "..."}) are returned as-is — there
is no expires_at to compare against, so we trust the token until Todoist
itself rejects it (in which case the route layer surfaces
todoist_reconnect_required to the user).
"""

from __future__ import annotations

import logging
import time

import requests

from api.config import settings

logger = logging.getLogger(__name__)

# Refresh window: if the access token expires within this many seconds, refresh
# proactively before using it. Generous to absorb network latency on the
# Todoist API call itself.
_REFRESH_WINDOW_SECONDS = 300  # 5 minutes

_TODOIST_TOKEN_URL = "https://api.todoist.com/oauth/access_token"


class TodoistTokenError(Exception):
    """Raised when a valid token cannot be obtained or refreshed.
    Caller should surface this as `todoist_reconnect_required` to the user."""


def get_valid_todoist_token(supabase, user_id: str) -> str:
    """Return a valid (unexpired) access_token for the user, refreshing if
    near expiry. Updates Supabase with the rotated refresh_token on success.

    Raises TodoistTokenError when no token is stored, the refresh request is
    rejected (revoked / rotated by another request / etc.), or the network
    call to Todoist's token endpoint fails."""
    row = (
        supabase.from_("users")
        .select("todoist_oauth_token")
        .eq("id", user_id)
        .single()
        .execute()
    )
    blob = (row.data or {}).get("todoist_oauth_token") or {}
    access_token = blob.get("access_token")
    refresh_token = blob.get("refresh_token")
    expires_at = blob.get("expires_at")

    if not access_token:
        raise TodoistTokenError("No Todoist token stored for user")

    # Legacy long-lived token (no expires_at) — return as-is.
    if expires_at is None:
        return access_token

    now = int(time.time())
    if now < (expires_at - _REFRESH_WINDOW_SECONDS):
        return access_token

    # Need to refresh
    if not refresh_token:
        raise TodoistTokenError(
            "Todoist token expired and no refresh_token available — user must reconnect"
        )

    try:
        resp = requests.post(
            _TODOIST_TOKEN_URL,
            data={
                "client_id": settings.TODOIST_CLIENT_ID,
                "client_secret": settings.TODOIST_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.warning("[todoist_token] refresh network error: %s", exc)
        raise TodoistTokenError(f"Refresh network error: {exc}") from exc

    if resp.status_code != 200:
        # 400 / 401 = refresh_token rejected (revoked, rotated by another req, etc.)
        logger.warning(
            "[todoist_token] refresh failed: status=%s body=%s",
            resp.status_code,
            resp.text[:200],
        )
        raise TodoistTokenError(
            f"Refresh rejected by Todoist (status {resp.status_code})"
        )

    payload = resp.json()
    new_access = payload.get("access_token")
    # Todoist rotates refresh_token on every refresh; fall back to the old one
    # only if the response omits it (defensive — spec says it'll always be present).
    new_refresh = payload.get("refresh_token") or refresh_token
    new_expires_at = int(time.time()) + payload.get("expires_in", 3600)

    if not new_access:
        raise TodoistTokenError("Refresh response missing access_token")

    new_blob = {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": new_expires_at,
        "token_type": payload.get("token_type", "Bearer"),
    }
    supabase.from_("users").update(
        {"todoist_oauth_token": new_blob}
    ).eq("id", user_id).execute()
    return new_access
