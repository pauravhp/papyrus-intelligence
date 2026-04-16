"""
GET  /api/calendars            — list user's GCal calendars with metadata
PATCH /api/settings/calendars  — save source_calendar_ids, write_calendar_id, nudge_dismissed
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.config import settings
from api.db import supabase
from src.calendar_client import build_gcal_service_from_credentials, list_calendars

router = APIRouter(prefix="/api")


def _get_gcal_service(user_id: str):
    """Load GCal service for user. Raises 400 if not connected."""
    row = (
        supabase.from_("users")
        .select("google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    gcal_creds = (row.data or {}).get("google_credentials")
    if not gcal_creds:
        raise HTTPException(status_code=400, detail="Google Calendar not connected")
    svc, refreshed = build_gcal_service_from_credentials(
        gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    )
    if refreshed:
        supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
    return svc


@router.get("/calendars")
def get_calendars(user: dict = Depends(get_current_user)) -> list[dict]:
    """Return all GCal calendars for the authenticated user."""
    user_id: str = user["sub"]
    svc = _get_gcal_service(user_id)
    return list_calendars(svc)


class CalendarSettingsRequest(BaseModel):
    source_calendar_ids: list[str] | None = None
    write_calendar_id: str | None = None
    nudge_dismissed: bool | None = None


@router.patch("/settings/calendars")
def patch_calendar_settings(
    body: CalendarSettingsRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Save calendar selection. Any field may be omitted — only provided fields are updated."""
    user_id: str = user["sub"]

    if body.source_calendar_ids is not None and len(body.source_calendar_ids) == 0:
        raise HTTPException(status_code=422, detail="source_calendar_ids must not be empty")

    if body.write_calendar_id is not None:
        svc = _get_gcal_service(user_id)
        cals = list_calendars(svc)
        writable_ids = {c["id"] for c in cals if c["access_role"] in ("owner", "writer")}
        if body.write_calendar_id not in writable_ids:
            raise HTTPException(status_code=422, detail="write_calendar_id must be a writable calendar")

    row = (
        supabase.from_("users")
        .select("config")
        .eq("id", user_id)
        .single()
        .execute()
    )
    config: dict = ((row.data or {}).get("config") or {}).copy()

    if body.source_calendar_ids is not None:
        config["source_calendar_ids"] = body.source_calendar_ids
    if body.write_calendar_id is not None:
        config["write_calendar_id"] = body.write_calendar_id
    if body.nudge_dismissed:
        nudges = dict(config.get("nudges") or {})
        nudges["calendar_dismissed"] = True
        config["nudges"] = nudges

    supabase.from_("users").update({"config": config}).eq("id", user_id).execute()
    return {"ok": True}
