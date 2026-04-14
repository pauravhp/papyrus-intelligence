"""
GET /api/today — Return confirmed schedule_log entries for yesterday, today, tomorrow.

Only returns entries where confirmed = 1 (written to GCal).
For each date, returns the most recent confirmed entry (highest id).
"""
import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user
from api.db import supabase

router = APIRouter(prefix="/api")


def _parse_day(row: dict | None) -> dict | None:
    """Parse a schedule_log row into a clean day dict. Returns None if no row."""
    if not row or not row.get("proposed_json"):
        return None
    try:
        parsed = json.loads(row["proposed_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return {
        "schedule_date": row["schedule_date"],
        "scheduled": parsed.get("scheduled", []),
        "pushed": parsed.get("pushed", []),
        "confirmed_at": row.get("confirmed_at"),
    }


@router.get("/today")
def get_today_view(user: dict = Depends(get_current_user)) -> dict:
    """
    Returns confirmed schedules for yesterday, today, and tomorrow.
    Uses idx_schedule_log_user_date index for efficiency.
    """
    user_id: str = user["sub"]
    today = date.today()
    dates = [
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
        (today + timedelta(days=1)).isoformat(),
    ]

    result = (
        supabase.from_("schedule_log")
        .select("schedule_date, proposed_json, confirmed_at")
        .eq("user_id", user_id)
        .in_("schedule_date", dates)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .execute()
    )

    # Group by date — first row per date is the most recent (desc order)
    by_date: dict[str, dict] = {}
    for row in (result.data or []):
        d = row["schedule_date"]
        if d not in by_date:
            by_date[d] = row

    return {
        "yesterday": _parse_day(by_date.get(dates[0])),
        "today":     _parse_day(by_date.get(dates[1])),
        "tomorrow":  _parse_day(by_date.get(dates[2])),
    }
