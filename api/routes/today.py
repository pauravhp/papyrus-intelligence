"""
GET /api/today — Return confirmed schedule_log entries for yesterday, today, tomorrow.

Only returns entries where confirmed = 1 (written to GCal).
For each date, returns the most recent confirmed entry (highest id).
"""
import json
import logging
from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user
from api.db import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _get_now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_review_available(user_config: dict, has_confirmed_schedule: bool) -> bool:
    """Returns True if review cutoff has passed and a confirmed schedule exists."""
    if not has_confirmed_schedule:
        return False
    tz_name = user_config.get("user", {}).get("timezone", "UTC")
    sleep_time_str = user_config.get("user", {}).get("sleep_time", "23:00")
    try:
        tz = ZoneInfo(tz_name)
        now_local = _get_now().astimezone(tz)
        h, m = map(int, sleep_time_str.split(":"))
        sleep_dt = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        cutoff = sleep_dt - timedelta(hours=2, minutes=30)
        return now_local >= cutoff
    except Exception:
        logger.warning("Failed to compute review cutoff, defaulting to False")
        return False


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

    # Fetch user config for review_available computation
    config = {}
    try:
        user_row = (
            supabase.from_("users")
            .select("config")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if user_row.data:
            config = user_row.data.get("config") or {}
    except Exception:
        pass  # review_available defaults to False

    # Check if a confirmed schedule exists (separate, simple query)
    schedule_check = (
        supabase.from_("schedule_log")
        .select("id")
        .eq("user_id", user_id)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    has_confirmed_schedule = bool(schedule_check.data)

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
        "review_available": _compute_review_available(config, has_confirmed_schedule),
    }
