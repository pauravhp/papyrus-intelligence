"""
PATCH /api/settings/nudges     — toggle coaching nudge flags
PATCH /api/settings/calendars  — update source/write calendar IDs and calendar rules
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase

router = APIRouter()


# ── Nudges ────────────────────────────────────────────────────────────────────

class NudgesPayload(BaseModel):
    coaching_enabled: Optional[bool] = None
    weekly_reflection_enabled: Optional[bool] = None


@router.patch("/api/settings/nudges")
def patch_nudges(
    payload: NudgesPayload,
    user: dict = Depends(get_current_user),
) -> dict:
    user_id: str = user["sub"]

    row = (
        supabase.from_("users")
        .select("config")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    config: dict = (row.data or {}).get("config") or {}
    nudges: dict = dict(config.get("nudges") or {})

    if payload.coaching_enabled is not None:
        nudges["coaching_enabled"] = payload.coaching_enabled
    if payload.weekly_reflection_enabled is not None:
        nudges["weekly_reflection_enabled"] = payload.weekly_reflection_enabled

    config["nudges"] = nudges
    supabase.from_("users").update({"config": config}).eq("id", user_id).execute()
    return {"nudges": nudges}


# ── Calendars ─────────────────────────────────────────────────────────────────

class CalendarsPayload(BaseModel):
    source_calendar_ids: Optional[list[str]] = None
    write_calendar_id: Optional[str] = None
    calendar_rules: Optional[dict] = None


@router.patch("/api/settings/calendars")
def patch_calendars(
    payload: CalendarsPayload,
    user: dict = Depends(get_current_user),
) -> dict:
    user_id: str = user["sub"]

    row = (
        supabase.from_("users")
        .select("config")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    config: dict = dict((row.data or {}).get("config") or {})

    if payload.source_calendar_ids is not None:
        config["source_calendar_ids"] = payload.source_calendar_ids
    if payload.write_calendar_id is not None:
        config["write_calendar_id"] = payload.write_calendar_id
    if payload.calendar_rules is not None:
        config["calendar_rules"] = payload.calendar_rules

    supabase.from_("users").update({"config": config}).eq("id", user_id).execute()
    return {
        "source_calendar_ids": config.get("source_calendar_ids"),
        "write_calendar_id": config.get("write_calendar_id"),
        "calendar_rules": config.get("calendar_rules"),
    }
