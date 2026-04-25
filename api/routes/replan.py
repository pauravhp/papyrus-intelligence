"""
POST /api/replan          — propose a new afternoon schedule (no writes)
POST /api/replan/confirm  — commit proposed schedule to GCal + Todoist
POST /api/replan/preflight — check which tasks Todoist marks as completed
"""

import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.config import settings
from api.db import supabase
from api.services.analytics import capture
from src.calendar_client import build_gcal_service_from_credentials, create_event, delete_event, get_events
from src.scheduler import compute_free_windows
from api.services.schedule_service import schedule_day
from src.todoist_client import TodoistClient

router = APIRouter(prefix="/api")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_now() -> datetime:
    """Thin wrapper so tests can patch it."""
    return datetime.now()


def _sanitize_note(note: str | None, max_chars: int = 300) -> str:
    if not note:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", note)
    # Normalize whitespace
    clean = " ".join(clean.split())
    return clean[:max_chars]


def _load_user_context(user_id: str) -> dict:
    """Mirror of chat.py _load_user_context — load config + Todoist + GCal."""
    row_result = (
        supabase.from_("users")
        .select("config, todoist_oauth_token, google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=400, detail="User not found or not onboarded.")

    row = row_result.data
    config = row.get("config") or {}
    tod_token: str | None = (row.get("todoist_oauth_token") or {}).get("access_token")

    gcal_creds = row.get("google_credentials")
    gcal_service = None
    if gcal_creds:
        try:
            svc, refreshed = build_gcal_service_from_credentials(
                gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
            )
            gcal_service = svc
            if refreshed:
                supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
        except Exception as exc:
            print(f"[replan] GCal service init failed: {exc}")

    return {
        "user_id": user_id,
        "config": config,
        "todoist_api_key": tod_token,
        "gcal_service": gcal_service,
        "supabase": supabase,
    }


def _load_today_schedule(user_id: str) -> dict | None:
    """Load most recent confirmed schedule_log row for today."""
    result = (
        supabase.from_("schedule_log")
        .select("id, proposed_json, gcal_event_ids, gcal_write_calendar_id, schedule_date, confirmed_at")
        .eq("user_id", user_id)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    row = rows[0]
    if row.get("schedule_date") != date.today().isoformat():
        return None
    return row


# ── Models ────────────────────────────────────────────────────────────────────

class ReplanRequest(BaseModel):
    task_states: dict[str, str]        # task_id -> "done" | "tomorrow" | "keep"
    context_note: str | None = None
    refinement_message: str | None = None


class ReplanConfirmRequest(BaseModel):
    schedule: dict                     # {"scheduled": [...], "pushed": [...]}
    tomorrow_task_ids: list[str] = []


class ReplanPreflightRequest(BaseModel):
    task_ids: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/replan")
def replan(body: ReplanRequest, user: dict = Depends(get_current_user)) -> dict:
    """Propose a new afternoon schedule. No external writes."""
    user_id: str = user["sub"]

    now = _get_now()
    if now.hour < 12:
        raise HTTPException(status_code=400, detail="Replan is only available after noon (before noon is not supported).")

    user_ctx = _load_user_context(user_id)
    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    tz = ZoneInfo(tz_str)

    today_row = _load_today_schedule(user_id)
    if not today_row:
        raise HTTPException(status_code=400, detail="No confirmed schedule found for today.")

    try:
        schedule = json.loads(today_row["proposed_json"])
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Could not parse today's schedule.")

    # Determine afternoon tasks (start_time >= now)
    now_aware = now.astimezone(tz)
    afternoon_tasks_raw = [
        item for item in schedule.get("scheduled", [])
        if datetime.fromisoformat(item["start_time"]).astimezone(tz) >= now_aware
    ]

    # Build effective states: start from request, auto-promote if Todoist says completed
    todoist_client = TodoistClient(user_ctx["todoist_api_key"])
    effective_states: dict[str, str] = {}
    for item in afternoon_tasks_raw:
        tid = item["task_id"]
        requested_state = body.task_states.get(tid, "keep")
        if requested_state == "keep":
            try:
                if todoist_client.is_task_completed(tid):
                    requested_state = "done"
            except Exception:
                pass  # Todoist unavailable — trust the user's state
        effective_states[tid] = requested_state

    # Build task list for scheduler: "keep" tasks from today's schedule
    from src.models import TodoistTask
    today_task_ids: set[str] = {item["task_id"] for item in afternoon_tasks_raw}
    keep_tasks: list[TodoistTask] = []
    for item in afternoon_tasks_raw:
        tid = item["task_id"]
        if effective_states.get(tid) == "keep":
            keep_tasks.append(
                TodoistTask(
                    id=tid,
                    content=item["task_name"],
                    priority=2,
                    duration_minutes=item["duration_minutes"],
                    due_datetime=None,
                    deadline=None,
                    labels=[],
                    project_id=None,
                    is_inbox=False,
                    is_rhythm=False,
                    session_max_minutes=None,
                    sessions_per_week=None,
                )
            )

    # Also fetch backlog Todoist tasks (not already in today's schedule) as additional candidates.
    # This allows replanning even when all today's tasks are marked done/tomorrow.
    backlog_tasks: list[TodoistTask] = []
    if user_ctx["todoist_api_key"]:
        try:
            raw_tasks = TodoistClient(user_ctx["todoist_api_key"]).get_tasks()
            for t in raw_tasks:
                if t.id not in today_task_ids:
                    backlog_tasks.append(t)
        except Exception as exc:
            print(f"[replan] Backlog fetch failed: {exc}")

    candidate_tasks = keep_tasks + backlog_tasks

    # Compute free windows from now → end of day
    today_str = date.today().isoformat()
    cal_ids = (
        config.get("source_calendar_ids")
        or config.get("calendar_ids")
        or ["primary"]
    )
    events = []
    if user_ctx["gcal_service"]:
        try:
            events = get_events(
                date.today(), tz_str, calendar_ids=cal_ids,
                service=user_ctx["gcal_service"],
            )
        except Exception as exc:
            print(f"[replan] get_events failed: {exc}")

    all_windows = compute_free_windows(events, date.today(), config)
    # Filter to windows that end after now (both tz-aware datetimes in user's local tz)
    afternoon_windows = [w for w in all_windows if w.end > now_aware]

    # Inject mid-day hard rule so LLM knows current time
    config_with_time = dict(config)
    rules = dict(config_with_time.get("rules", {}))
    hard_rules = list(rules.get("hard", []))
    current_time_rule = f"It is currently {now_aware.strftime('%H:%M')}. Schedule only from now onwards."
    hard_rules.insert(0, current_time_rule)
    rules["hard"] = hard_rules
    config_with_time["rules"] = rules
    print(f"[replan] now_aware={now_aware.isoformat()} | injected: {current_time_rule}")

    # Build context note: refinement is primary, original note is background
    context_note = _sanitize_note(body.context_note)
    refinement = _sanitize_note(body.refinement_message)
    if refinement and context_note:
        combined_note = f"{refinement}\n\n[Background context: {context_note}]"
    elif refinement:
        combined_note = refinement
    else:
        combined_note = context_note

    proposed = schedule_day(
        tasks=candidate_tasks,
        free_windows=afternoon_windows,
        config=config_with_time,
        context_note=combined_note,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        target_date=today_str,
        events=events,
    )

    return proposed


@router.post("/replan/confirm")
def replan_confirm(body: ReplanConfirmRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)) -> dict:
    """Commit the proposed afternoon schedule to GCal + Todoist."""
    user_id: str = user["sub"]

    user_ctx = _load_user_context(user_id)
    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    write_cal_id = config.get("write_calendar_id", "primary")
    tz = ZoneInfo(tz_str)
    todoist_client = TodoistClient(user_ctx["todoist_api_key"])

    # Push "tomorrow" tasks
    for tid in body.tomorrow_task_ids:
        try:
            todoist_client.clear_task_due(tid)
            todoist_client.add_comment(tid, "Pushed: Moved to tomorrow during mid-day replan")
        except Exception as exc:
            print(f"[replan/confirm] push_task failed for {tid}: {exc}")

    # Load today's schedule_log to get stored gcal_event_ids
    today_row = _load_today_schedule(user_id)
    gcal_event_ids: list[str] = []
    write_cal_from_log = "primary"
    if today_row:
        try:
            gcal_event_ids = json.loads(today_row.get("gcal_event_ids") or "[]")
        except (json.JSONDecodeError, TypeError):
            gcal_event_ids = []
        write_cal_from_log = (today_row or {}).get("gcal_write_calendar_id") or "primary"

    # Delete only afternoon GCal events (start_time >= now)
    now_aware = datetime.now().astimezone(tz)
    for event_id in gcal_event_ids:
        try:
            # Fetch event to check its start time before deleting
            event = user_ctx["gcal_service"].events().get(
                calendarId=write_cal_from_log, eventId=event_id
            ).execute()
            start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            if start_str:
                start_dt = datetime.fromisoformat(start_str).astimezone(tz)
                if start_dt >= now_aware:
                    delete_event(user_ctx["gcal_service"], event_id, calendar_id=write_cal_from_log)
        except Exception as exc:
            # 404 = already deleted by user; skip gracefully
            if "404" not in str(exc) and "notFound" not in str(exc):
                print(f"[replan/confirm] GCal delete check failed for {event_id}: {exc}")

    # Create new GCal events + update Todoist due_datetime
    import json as _json
    from datetime import datetime as _dt
    new_gcal_ids: list[str] = []
    todoist_count = 0

    for item in body.schedule.get("scheduled", []):
        try:
            start_dt = datetime.fromisoformat(item["start_time"])
            end_dt = datetime.fromisoformat(item["end_time"])
            gcal_id = create_event(
                user_ctx["gcal_service"],
                title=item["task_name"],
                start_dt=start_dt,
                end_dt=end_dt,
                timezone_str=tz_str,
                calendar_id=write_cal_id,
            )
            new_gcal_ids.append(gcal_id)
        except Exception as exc:
            print(f"[replan/confirm] GCal create failed for {item.get('task_name')}: {exc}")

        if not item.get("task_id", "").startswith("proj_"):
            try:
                start_dt = datetime.fromisoformat(item["start_time"])
                todoist_client.schedule_task(
                    item["task_id"], start_dt, item["duration_minutes"]
                )
                todoist_count += 1
            except Exception as exc:
                print(f"[replan/confirm] Todoist update failed for {item.get('task_id')}: {exc}")

    # Insert new confirmed schedule_log row
    supabase.from_("schedule_log").insert({
        "user_id": user_id,
        "run_at": _dt.now().isoformat(),
        "schedule_date": date.today().isoformat(),
        "proposed_json": _json.dumps(body.schedule),
        "confirmed": 1,
        "confirmed_at": _dt.now().isoformat(),
        "gcal_event_ids": _json.dumps(new_gcal_ids),
        "gcal_write_calendar_id": write_cal_id,
        "replan_trigger": "mid_day_replan",
    }).execute()

    tasks_kept = len(body.schedule.get("scheduled", []))
    tasks_pushed = len(body.tomorrow_task_ids)
    background_tasks.add_task(
        capture,
        user_id,
        "replan_confirmed",
        {
            "tasks_kept": tasks_kept,
            "tasks_pushed": tasks_pushed,
        },
    )

    return {
        "confirmed": True,
        "gcal_events_created": len(new_gcal_ids),
        "todoist_updated": todoist_count,
    }


@router.post("/replan/preflight")
def replan_preflight(body: ReplanPreflightRequest, user: dict = Depends(get_current_user)) -> dict:
    """Check which task IDs are already completed in Todoist."""
    user_id: str = user["sub"]
    user_ctx = _load_user_context(user_id)
    todoist_client = TodoistClient(user_ctx["todoist_api_key"])

    completed_ids: list[str] = []
    for tid in body.task_ids:
        try:
            if todoist_client.is_task_completed(tid):
                completed_ids.append(tid)
        except Exception:
            pass  # Skip on error — user can toggle manually

    return {"completed_ids": completed_ids}
