"""
GET /api/today — Return confirmed schedule_log entries for yesterday, today, tomorrow.

Only returns entries where confirmed = 1 (written to GCal).
For each date, returns the most recent confirmed entry (highest id).
GCal events are fetched live for each day and returned alongside confirmed schedule data.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user
from api.config import settings
from api.db import supabase
from src.calendar_client import build_gcal_service_from_credentials, get_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _get_now() -> datetime:
    """Thin wrapper so tests can patch it."""
    return datetime.now(timezone.utc)


def _compute_review_available(user_config: dict, has_confirmed_schedule: bool) -> bool:
    """Returns True if review cutoff has passed and a confirmed schedule exists today."""
    if not has_confirmed_schedule:
        return False
    tz_name = user_config.get("user", {}).get("timezone", "UTC")
    sleep_time_str = user_config.get("user", {}).get("sleep_time", "23:00")
    if not sleep_time_str:
        logger.warning("sleep_time missing from user config, defaulting to 23:00")
        sleep_time_str = "23:00"
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


def _papyrus_ids(row: dict | None) -> set[str]:
    """Parse gcal_event_ids JSON from a schedule_log row. Returns empty set on failure."""
    if not row:
        return set()
    raw = row.get("gcal_event_ids") or "[]"
    try:
        return set(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return set()


def _fetch_gcal_for_date(
    target_date: date,
    tz_str: str,
    cal_ids: list,
    gcal_service,
    papyrus_event_ids: set[str],
) -> tuple[list[dict], list[str]]:
    """Fetch GCal events for one day. Returns (timed_events, all_day_names).
    Returns ([], []) if service is None or the GCal call fails.
    """
    if not gcal_service:
        return [], []
    try:
        events = get_events(
            target_date=target_date,
            timezone_str=tz_str,
            extra_calendar_ids=cal_ids,
            service=gcal_service,
        )
    except Exception:
        logger.warning("GCal read failed for %s", target_date)
        return [], []
    timed: list[dict] = []
    all_day: list[str] = []
    for e in events:
        if e.id in papyrus_event_ids:
            continue
        if e.is_all_day:
            all_day.append(e.summary)
        else:
            timed.append({
                "id": e.id,
                "summary": e.summary,
                "start_time": e.start.isoformat(),
                "end_time": e.end.isoformat(),
            })
    return timed, all_day


def _parse_day(
    row: dict | None,
    target_date: str,
    gcal_events: list[dict],
    all_day_events: list[str],
) -> dict | None:
    """Parse schedule_log row + gcal data into a day dict. Returns None if no data at all."""
    has_schedule = row and row.get("proposed_json")
    has_gcal = bool(gcal_events or all_day_events)
    if not has_schedule and not has_gcal:
        return None
    if has_schedule:
        try:
            parsed = json.loads(row["proposed_json"])
        except (json.JSONDecodeError, TypeError):
            parsed = {}
    else:
        parsed = {}
    return {
        "schedule_date": target_date,
        "scheduled": parsed.get("scheduled", []),
        "pushed": parsed.get("pushed", []),
        "confirmed_at": (row or {}).get("confirmed_at"),
        "gcal_events": gcal_events,
        "all_day_events": all_day_events,
    }


@router.get("/today")
def get_today_view(user: dict = Depends(get_current_user)) -> dict:
    """
    Returns confirmed schedules for yesterday, today, and tomorrow.
    GCal events are fetched live for each day and merged into the response.
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
        .select("schedule_date, proposed_json, confirmed_at, gcal_event_ids")
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

    # Fetch user config + google credentials
    config: dict = {}
    gcal_service = None
    try:
        user_row = (
            supabase.from_("users")
            .select("config, google_credentials")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if user_row.data:
            config = user_row.data.get("config") or {}
            gcal_creds = user_row.data.get("google_credentials")
            if gcal_creds:
                try:
                    svc, refreshed = build_gcal_service_from_credentials(
                        gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
                    )
                    gcal_service = svc
                    if refreshed:
                        supabase.from_("users").update(
                            {"google_credentials": refreshed}
                        ).eq("id", user_id).execute()
                except Exception as e:
                    logger.warning("Failed to build GCal service for user %s: %s", user_id, e)
    except Exception:
        pass  # review_available defaults to False on error

    # Check if a confirmed schedule exists for today (separate lightweight query)
    today_str = dates[1]  # dates[1] is today's iso string
    schedule_check = (
        supabase.from_("schedule_log")
        .select("id")
        .eq("user_id", user_id)
        .eq("schedule_date", today_str)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    has_confirmed_schedule = bool(schedule_check.data)

    # Fetch GCal events for each day
    tz_str = config.get("user", {}).get("timezone", "UTC")
    cal_ids = config.get("calendar_ids", [])
    date_objs = [today - timedelta(days=1), today, today + timedelta(days=1)]

    gcal_results: list[tuple[list, list]] = []
    for d_obj, d_str in zip(date_objs, dates):
        papyrus_event_ids = _papyrus_ids(by_date.get(d_str))
        gcal_results.append(
            _fetch_gcal_for_date(d_obj, tz_str, cal_ids, gcal_service, papyrus_event_ids)
        )

    return {
        "yesterday": _parse_day(by_date.get(dates[0]), dates[0], gcal_results[0][0], gcal_results[0][1]),
        "today":     _parse_day(by_date.get(dates[1]), dates[1], gcal_results[1][0], gcal_results[1][1]),
        "tomorrow":  _parse_day(by_date.get(dates[2]), dates[2], gcal_results[2][0], gcal_results[2][1]),
        "review_available": _compute_review_available(config, has_confirmed_schedule),
    }
