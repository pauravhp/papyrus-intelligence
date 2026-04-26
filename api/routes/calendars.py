"""
GET  /api/calendars            — list user's GCal calendars with metadata
"""

from fastapi import APIRouter, Depends, HTTPException
from google.auth.exceptions import RefreshError

from api.auth import get_current_user, require_beta_access
from api.config import settings
from api.db import supabase
from src.calendar_client import build_gcal_service_from_credentials, list_calendars

router = APIRouter(prefix="/api")


def _get_gcal_service(user_id: str):
    """Load GCal service for user. Raises 400 if not connected or needs reconnect."""
    row = (
        supabase.from_("users")
        .select("google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    gcal_creds = (row.data or {}).get("google_credentials")
    if not gcal_creds:
        raise HTTPException(
            status_code=400,
            detail={"code": "google_not_connected", "message": "Google Calendar not connected"},
        )
    try:
        svc, refreshed = build_gcal_service_from_credentials(
            gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        )
    except RefreshError:
        raise HTTPException(
            status_code=400,
            detail={"code": "google_reconnect_required", "message": "Google refresh token revoked or expired"},
        )
    if refreshed:
        supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
    return svc


@router.get("/calendars")
def get_calendars(user: dict = Depends(require_beta_access)) -> list[dict]:
    """Return all GCal calendars for the authenticated user."""
    user_id: str = user["sub"]
    svc = _get_gcal_service(user_id)
    return list_calendars(svc)



