"""
Find-or-create the user's "Papyrus" GCal calendar.

Idempotent: caches the calendar id on users.papyrus_calendar_id so
subsequent calls skip the GCal list + create round-trips entirely.

Scope: requires `calendar.app.created` (added in Task 7). If the user's
credentials don't carry that scope yet, raises PapyrusCalendarScopeError
which the route maps to a `calendar_scope_upgrade_required` flag on
the response.
"""
from __future__ import annotations

import logging

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

PAPYRUS_CALENDAR_SUMMARY = "Papyrus"
PAPYRUS_CALENDAR_DESCRIPTION = (
    "Created automatically by Papyrus to keep your scheduled focus blocks "
    "separate from your other calendars."
)
PAPYRUS_CALENDAR_COLOR_ID = "9"
APP_CREATED_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"


class PapyrusCalendarError(RuntimeError):
    """Generic failure during calendar find-or-create."""


class PapyrusCalendarScopeError(PapyrusCalendarError):
    """User's OAuth credentials lack `calendar.app.created`. The route surfaces
    this as `calendar_scope_upgrade_required: true` so the frontend can
    prompt re-consent inline at Step 8."""


def _has_app_created_scope(credentials) -> bool:
    scopes = list(getattr(credentials, "scopes", None) or [])
    return APP_CREATED_SCOPE in scopes


def _read_cached_id(user_id: str, supabase) -> str | None:
    try:
        row = (
            supabase.from_("users")
            .select("papyrus_calendar_id")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return (row.data or {}).get("papyrus_calendar_id")
    except Exception:
        return None


def _persist_id(user_id: str, supabase, calendar_id: str) -> None:
    try:
        supabase.from_("users").update(
            {"papyrus_calendar_id": calendar_id}
        ).eq("id", user_id).execute()
    except Exception:
        logger.exception("[import_calendar] failed to persist calendar_id for user %s", user_id)


def _find_existing_papyrus_calendar(service) -> str | None:
    resp = service.calendarList().list().execute()
    for item in resp.get("items", []):
        if (item.get("summary") or "").strip() == PAPYRUS_CALENDAR_SUMMARY:
            return item.get("id")
    return None


def _create_papyrus_calendar(service, timezone_str: str) -> str:
    body = {
        "summary": PAPYRUS_CALENDAR_SUMMARY,
        "description": PAPYRUS_CALENDAR_DESCRIPTION,
        "timeZone": timezone_str or "UTC",
    }
    created = service.calendars().insert(body=body).execute()
    cal_id = created.get("id")
    if not cal_id:
        raise PapyrusCalendarError("Calendar create returned no id")
    try:
        service.calendarList().patch(
            calendarId=cal_id,
            body={"colorId": PAPYRUS_CALENDAR_COLOR_ID},
        ).execute()
    except Exception:
        logger.warning("[import_calendar] color set failed for %s — non-fatal", cal_id)
    return cal_id


def ensure_papyrus_calendar(
    *,
    user_id: str,
    supabase,
    credentials,
    timezone_str: str,
) -> str:
    """Return the id of the user's Papyrus calendar, creating it if needed."""
    cached = _read_cached_id(user_id, supabase)
    if cached:
        return cached

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    existing = _find_existing_papyrus_calendar(service)
    if existing:
        _persist_id(user_id, supabase, existing)
        return existing

    if not _has_app_created_scope(credentials):
        raise PapyrusCalendarScopeError(
            "User credentials lack calendar.app.created — re-OAuth required."
        )

    new_id = _create_papyrus_calendar(service, timezone_str)
    _persist_id(user_id, supabase, new_id)
    return new_id
