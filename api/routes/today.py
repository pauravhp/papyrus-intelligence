"""
GET /api/today — Return confirmed schedule_log entries for yesterday, today, tomorrow.

Only returns entries where confirmed = 1 (written to GCal).
For each date, returns the most recent confirmed entry (highest id).
GCal events are fetched live for each day and returned alongside confirmed schedule data.
"""
import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import get_current_user, require_beta_access
from api.config import settings
from api.db import supabase
from src.calendar_client import (
    GcalReconnectRequired,
    build_gcal_service_from_credentials,
    get_events_range,
)
from src.todoist_client import TodoistClient
from api.services.reconcile_service import reconcile_today
from api.services.todoist_token import get_valid_todoist_token, TodoistTokenError

logger = logging.getLogger(__name__)

# Maps GCal event colorId strings to hex colors (Google Calendar palette)
GCAL_COLOR_HEX: dict[str, str] = {
    "1": "#ac725e", "2": "#d06b64", "3": "#f83a22", "4": "#fa573c",
    "5": "#ff7537", "6": "#ffad46", "7": "#42d692", "8": "#16a765",
    "9": "#7bd148", "10": "#b3dc6c", "11": "#fbe983",
}

router = APIRouter(prefix="/api")


def _get_now() -> datetime:
    """Thin wrapper so tests can patch it."""
    return datetime.now(timezone.utc)


def _cutoff_passed(user_config: dict) -> bool:
    """Returns True if current local time has passed the review cutoff (sleep_time − 2:30)."""
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


def _compute_review_available(user_config: dict, has_confirmed_schedule: bool) -> bool:
    """Returns True if review cutoff has passed and a confirmed schedule exists today."""
    return has_confirmed_schedule and _cutoff_passed(user_config)


def _compute_review_queue(user_id: str, today_local: date, cutoff_passed: bool) -> dict:
    """Returns unreviewed confirmed schedule_log rows from the last 7 days, oldest first."""
    floor = (today_local - timedelta(days=7)).isoformat()
    upper = today_local.isoformat() if cutoff_passed else (today_local - timedelta(days=1)).isoformat()
    try:
        result = (
            supabase.from_("schedule_log")
            .select("schedule_date")
            .eq("user_id", user_id)
            .eq("confirmed", 1)
            .is_("reviewed_at", "null")
            .gte("schedule_date", floor)
            .lte("schedule_date", upper)
            .order("schedule_date", desc=False)
            .execute()
        )
    except Exception:
        logger.warning("[today] review_queue lookup failed", exc_info=True)
        return {"has_unreviewed": False, "count": 0, "dates": []}
    rows = result.data or []
    if not isinstance(rows, list):
        return {"has_unreviewed": False, "count": 0, "dates": []}
    dates = sorted({r["schedule_date"] for r in rows})
    return {"has_unreviewed": bool(dates), "count": len(dates), "dates": dates}


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
        logger.warning("[today] gcal_service is None for %s — skipping", target_date)
        return [], []
    try:
        events = get_events(
            target_date=target_date,
            timezone_str=tz_str,
            calendar_ids=cal_ids,
            service=gcal_service,
        )
    except Exception as exc:
        logger.warning("GCal read failed for %s: %s", target_date, exc)
        return [], []
    logger.debug("[today] %s: fetched %d events (cal_ids=%s, tz=%s)", target_date, len(events), cal_ids, tz_str)
    for e in events:
        logger.debug("[today]   event: %s | start=%s | all_day=%s | id=%s", e.summary, e.start.isoformat(), e.is_all_day, e.id)
    timed: list[dict] = []
    all_day: list[str] = []
    for e in events:
        if e.id in papyrus_event_ids:
            logger.debug("[today]   FILTERED (papyrus): %s", e.id)
            continue
        if e.is_all_day:
            all_day.append(e.summary)
        else:
            timed.append({
                "id": e.id,
                "summary": e.summary,
                "start_time": e.start.isoformat(),
                "end_time": e.end.isoformat(),
                "color_hex": GCAL_COLOR_HEX.get(e.color_id) if e.color_id else None,
            })
    return timed, all_day


def _tag_kind(scheduled: list[dict]) -> list[dict]:
    """Mark each scheduled item as 'task' or 'rhythm'.

    Synthetic rhythm tasks are prefixed with 'proj_' upstream by
    api/services/planner.py:266 (the synthetic TodoistTask id is
    f"proj_{rhythm['id']}"). Detect by prefix — no DB lookup needed.
    """
    out: list[dict] = []
    for item in scheduled:
        kind = "rhythm" if str(item.get("task_id", "")).startswith("proj_") else "task"
        out.append({**item, "kind": kind})
    return out


def get_user_calendars(user_id: str) -> tuple:
    """Fetch GCal service, calendar IDs, timezone, and config for a user.

    Returns (gcal_service, cal_ids, tz_str, todoist_connected,
    gcal_reconnect_required, config). The config dict is the user's full
    config — callers use it for cutoff/nudge logic without re-reading the
    users row.
    """
    gcal_service = None
    cal_ids = ["primary"]
    tz_str = "UTC"
    todoist_connected = False
    gcal_reconnect_required = False
    config: dict = {}
    try:
        user_row = (
            supabase.from_("users")
            .select("config, google_credentials, todoist_oauth_token")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if user_row.data:
            config = user_row.data.get("config") or {}
            todoist_connected = bool(
                (user_row.data.get("todoist_oauth_token") or {}).get("access_token")
            )
            tz_str = config.get("user", {}).get("timezone", "UTC")
            cal_ids = (
                config.get("source_calendar_ids")
                or config.get("calendar_ids")
                or ["primary"]
            )
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
                except GcalReconnectRequired as e:
                    logger.warning("[today] gcal reconnect required for user %s: %s", user_id, e)
                    gcal_reconnect_required = True
                except Exception as e:
                    logger.warning("Failed to build GCal service for user %s: %s", user_id, e)
    except Exception:
        pass
    return gcal_service, cal_ids, tz_str, todoist_connected, gcal_reconnect_required, config


def _fetch_day_gcal_events(
    target_date: date,
    gcal_service,
    cal_ids: list,
    tz_str: str,
    papyrus_event_ids: set[str],
) -> tuple[list[dict], list[str]]:
    """Thin wrapper around _fetch_gcal_for_date; patchable in tests."""
    return _fetch_gcal_for_date(target_date, tz_str, cal_ids, gcal_service, papyrus_event_ids)


def _bucket_events_by_day(
    events: list,
    target_dates: list[date],
    tz_str: str,
    papyrus_event_ids: set[str],
) -> tuple[list[tuple[list[dict], list[str]]], list[dict]]:
    """Bucket a flat list of CalendarEvents into per-day filtered views and an
    unfiltered today-events list (for reconcile).

    Each event is included in every day's bucket whose [00:00, 24:00) window
    in the user's tz overlaps the event — preserving the per-day-fetch
    semantics of the previous implementation, where a cross-midnight event
    appeared in both the start day's and end day's columns.

    Returns (per_day_results, today_unfiltered_dicts) where per_day_results
    is a list aligned to target_dates, each entry (timed_dicts, all_day_names)
    with papyrus events filtered out of the timed list.
    """
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")

    today_obj = target_dates[1] if len(target_dates) >= 2 else (target_dates[0] if target_dates else date.today())
    today_unfiltered: list[dict] = []

    per_day: list[tuple[list[dict], list[str]]] = []
    for d_obj in target_dates:
        day_start = datetime(d_obj.year, d_obj.month, d_obj.day, 0, 0, 0, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        timed: list[dict] = []
        all_day: list[str] = []
        for e in events:
            try:
                e_start = e.start.astimezone(tz) if e.start.tzinfo else e.start.replace(tzinfo=tz)
                e_end = e.end.astimezone(tz) if e.end.tzinfo else e.end.replace(tzinfo=tz)
            except Exception:
                continue
            if not (e_start < day_end and e_end > day_start):
                continue
            if e.is_all_day:
                all_day.append(e.summary)
            else:
                if e.id in papyrus_event_ids:
                    continue
                timed.append({
                    "id": e.id,
                    "summary": e.summary,
                    "start_time": e.start.isoformat(),
                    "end_time": e.end.isoformat(),
                    "color_hex": GCAL_COLOR_HEX.get(e.color_id) if e.color_id else None,
                })
        per_day.append((timed, all_day))

        if d_obj == today_obj:
            today_unfiltered = [
                {"id": e.id, "summary": e.summary,
                 "start_time": e.start.isoformat(), "end_time": e.end.isoformat()}
                for e in events
                if not e.is_all_day
                and e.start.astimezone(tz) < day_end
                and e.end.astimezone(tz) > day_start
            ]

    return per_day, today_unfiltered


def _fetch_gcal_range(
    start_date: date,
    end_date: date,
    gcal_service,
    cal_ids: list,
    tz_str: str,
) -> list:
    """Fetch GCal events for [start_date, end_date]. Returns [] on failure or
    when service/cal_ids are empty. Patchable in tests.
    """
    if not gcal_service or not cal_ids:
        return []
    try:
        return get_events_range(
            start_date=start_date,
            end_date=end_date,
            timezone_str=tz_str,
            calendar_ids=cal_ids,
            service=gcal_service,
        )
    except Exception:
        logger.warning("[today] GCal range fetch failed", exc_info=True)
        return []


def _fetch_todoist_for_today(user_id: str, today_obj: date) -> tuple[set[str], set[str], bool]:
    """Fetch Todoist active + completed task IDs for today. Returns
    (active_ids, completed_ids, ok). ok=True only if BOTH calls succeeded —
    callers must skip reconcile when ok=False (see commit c4dc74a).
    """
    try:
        tod_token = get_valid_todoist_token(supabase, user_id)
        tc = TodoistClient(tod_token)
        active = {str(t.id) for t in tc.get_tasks(filter_str="today")}
        completed = tc.get_completed_task_ids_for_date(today_obj)
        return active, completed, True
    except TodoistTokenError:
        logger.warning("[today] Todoist token invalid — skipping reconcile fetch")
    except Exception:
        logger.warning("[today] Todoist fetch for reconcile failed", exc_info=True)
    return set(), set(), False


def _fetch_schedule_log_window(user_id: str, dates: list[str]) -> list[dict]:
    """Read confirmed schedule_log rows for the given iso dates."""
    result = (
        supabase.from_("schedule_log")
        .select("schedule_date, proposed_json, confirmed_at, gcal_event_ids")
        .eq("user_id", user_id)
        .in_("schedule_date", dates)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .execute()
    )
    return result.data or []


def _fetch_today_row(user_id: str, today_str: str) -> dict | None:
    """Read the most recent confirmed schedule_log row for today, post-reconcile."""
    refreshed = (
        supabase.from_("schedule_log")
        .select("schedule_date, proposed_json, confirmed_at, gcal_event_ids")
        .eq("user_id", user_id)
        .eq("schedule_date", today_str)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if isinstance(refreshed.data, list) and refreshed.data and refreshed.data[0].get("proposed_json"):
        return refreshed.data[0]
    return None


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
        "scheduled": _tag_kind([s for s in (parsed.get("scheduled") or []) if not s.get("gcal_deleted")]),
        "pushed": parsed.get("pushed", []),
        "confirmed_at": (row or {}).get("confirmed_at"),
        "gcal_events": gcal_events,
        "all_day_events": all_day_events,
    }


@router.get("/today")
async def get_today_view(user: dict = Depends(require_beta_access)) -> dict:
    """
    Returns confirmed schedules for yesterday, today, and tomorrow.
    GCal events are fetched live for each day and merged into the response.
    Uses idx_schedule_log_user_date index for efficiency.

    Independent I/O is fanned out via asyncio.gather so total latency is
    dominated by the slowest hop, not their sum:
      Phase 1: users-row read (need user's tz before we know which 3 dates)
      Phase 2: schedule_log read ‖ GCal range ‖ Todoist (active+completed) ‖ review_queue
      Phase 3: reconcile + post-reconcile re-read (sequential — writes)
    """
    user_id: str = user["sub"]

    # ── Phase 1: user row first (we need the user's timezone) ─────────────────
    # `today` MUST be derived from the user's tz, not the server's. Servers
    # commonly run in UTC; without this, a user in PDT loading /today at
    # 5pm-ish their time (= past midnight UTC) sees their current day
    # rendered as "yesterday". Costs one Supabase RTT before we can fan out.
    user_data = await asyncio.to_thread(get_user_calendars, user_id)
    gcal_service, cal_ids, tz_str, todoist_connected, gcal_reconnect_required, config = user_data

    try:
        user_tz = ZoneInfo(tz_str)
    except Exception:
        user_tz = ZoneInfo("UTC")
    today = _get_now().astimezone(user_tz).date()
    today_obj = today
    date_objs = [today - timedelta(days=1), today, today + timedelta(days=1)]
    dates = [d.isoformat() for d in date_objs]
    today_str = dates[1]

    needs_calendar = not config.get("source_calendar_ids")
    needs_todoist = not todoist_connected
    dismissed = bool((config.get("nudges") or {}).get("calendar_dismissed"))
    setup_nudge = {
        "show": (needs_calendar or needs_todoist) and not dismissed,
        "needs_calendar": needs_calendar,
        "needs_todoist": needs_todoist,
    }

    cutoff = _cutoff_passed(config)

    # ── Phase 2: schedule_log + GCal + Todoist + review_queue (all parallel) ──
    # Single GCal range call covers all 3 days (was 4 separate calls — 3 for
    # display + 1 unfiltered duplicate for reconcile). The unfiltered today
    # slice is derived from the same response in _bucket_events_by_day.
    todoist_coro = (
        asyncio.to_thread(_fetch_todoist_for_today, user_id, today_obj)
        if todoist_connected
        else _noop_todoist()
    )
    schedule_rows, gcal_events_flat, todoist_data, review_queue = await asyncio.gather(
        asyncio.to_thread(_fetch_schedule_log_window, user_id, dates),
        asyncio.to_thread(
            _fetch_gcal_range, date_objs[0], date_objs[2], gcal_service, cal_ids, tz_str
        ),
        todoist_coro,
        asyncio.to_thread(_compute_review_queue, user_id, today, cutoff),
    )
    todoist_active_ids, todoist_completed_ids, todoist_fetch_ok = todoist_data

    # Group by date — first row per date is the most recent (desc order)
    by_date: dict[str, dict] = {}
    for row in (schedule_rows or []):
        d = row["schedule_date"]
        if d not in by_date:
            by_date[d] = row

    has_confirmed_schedule = today_str in by_date

    # Union papyrus_event_ids across ALL three days. A cross-midnight Papyrus
    # event written for yesterday's row also satisfies GCal's "events on
    # today" query (its end_time is in today's window), and would otherwise
    # double-render in today's column as a generic GCal block. Filtering by
    # the union ensures every column hides every Papyrus-written event.
    all_papyrus_ids: set[str] = set()
    for d_str in dates:
        all_papyrus_ids |= _papyrus_ids(by_date.get(d_str))

    gcal_results, today_gcal_dicts = _bucket_events_by_day(
        gcal_events_flat, date_objs, tz_str, all_papyrus_ids
    )

    # ── Phase 3: reconcile (writes — must run sequentially after fetches) ─────
    if not todoist_fetch_ok and todoist_connected:
        # Bail out of reconcile entirely. Without confirmed Todoist state we
        # can't tell deleted-in-Todoist apart from "API hiccup" and the
        # latter would silently destroy the user's schedule (see commit c4dc74a).
        logger.info("[today] skipping reconcile — Todoist fetch did not complete")
    else:
        try:
            await asyncio.to_thread(
                reconcile_today,
                {
                    "supabase": supabase,
                    "user_id": user_id,
                    "route": "today",
                    "gcal_events": today_gcal_dicts,
                    "todoist_active_ids": todoist_active_ids,
                    "todoist_completed_ids": todoist_completed_ids,
                },
                today_obj,
            )
            refreshed = await asyncio.to_thread(_fetch_today_row, user_id, today_str)
            if refreshed:
                by_date[today_str] = refreshed
        except Exception:
            logger.warning("[today] reconcile_today failed — serving pre-reconcile state", exc_info=True)

    return {
        "yesterday": _parse_day(by_date.get(dates[0]), dates[0], gcal_results[0][0], gcal_results[0][1]),
        "today":     _parse_day(by_date.get(dates[1]), dates[1], gcal_results[1][0], gcal_results[1][1]),
        "tomorrow":  _parse_day(by_date.get(dates[2]), dates[2], gcal_results[2][0], gcal_results[2][1]),
        "review_available": has_confirmed_schedule and cutoff,
        "setup_nudge": setup_nudge,
        "review_queue": review_queue,
        "gcal_reconnect_required": gcal_reconnect_required,
        "todoist_completed_ids": sorted(todoist_completed_ids),
    }


async def _noop_todoist() -> tuple[set[str], set[str], bool]:
    """Stand-in for the Todoist coroutine when the user has no Todoist
    connection — keeps the gather call uniform. todoist_fetch_ok=True so the
    reconcile guard does NOT skip (the guard targets *failed* fetches for
    *connected* users only)."""
    return set(), set(), True
