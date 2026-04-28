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

from api.auth import get_current_user, require_beta_access
from api.config import settings
from api.db import supabase
from api.services.analytics import capture
from api.services.planner import _is_within_idempotency_window
from api.services.todoist_token import (
    TodoistTokenError,
    get_valid_todoist_token,
    surface_todoist_auth_failure,
)
from src.calendar_client import build_gcal_service_from_credentials, create_event, delete_event, get_events
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
    has_stored_token = bool((row.get("todoist_oauth_token") or {}).get("access_token"))
    tod_token: str | None = None
    if has_stored_token:
        try:
            tod_token = get_valid_todoist_token(supabase, user_id)
        except TodoistTokenError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "todoist_reconnect_required", "message": str(exc)},
            )

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


# surface_todoist_auth_failure is imported from api.services.todoist_token —
# Lane A had to keep this local during parallel work; lifted in Lane E.


def _load_today_schedule(user_id: str) -> dict | None:
    """Load most recent confirmed schedule_log row for today."""
    result = (
        supabase.from_("schedule_log")
        .select("id, proposed_json, gcal_event_ids, gcal_write_calendar_id, schedule_date, confirmed_at, replan_trigger")
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
    previous_proposal: dict | None = None  # carries blocks + cutoff_override across in-modal refinements


class ReplanConfirmRequest(BaseModel):
    schedule: dict                     # {"scheduled": [...], "pushed": [...]}
    tomorrow_task_ids: list[str] = []


class ReplanPreflightRequest(BaseModel):
    task_ids: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/replan")
def replan(body: ReplanRequest, user: dict = Depends(require_beta_access)) -> dict:
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
                    project_id="",
                    is_inbox=False,
                    is_rhythm=False,
                    session_max_minutes=None,
                    sessions_per_week=None,
                )
            )

    # Also fetch backlog Todoist tasks (not already in today's schedule) so the
    # user can still replan when all of today's afternoon tasks are done/pushed.
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

    # Build prose for the extractor + scheduler. Mid-day note ("It is currently
    # HH:MM") is included so the scheduler LLM can reason about late-night
    # cutoffs. compute_free_windows already auto-detects mid-day and trims
    # the windows to start from now, so we don't need a hard-rule injection
    # like the legacy code did.
    note = _sanitize_note(body.context_note)
    refinement = _sanitize_note(body.refinement_message)
    parts = [f"It is currently {now_aware.strftime('%H:%M')} — schedule only from now."]
    if refinement:
        parts.append(f"Refinement: {refinement}")
    if note:
        parts.append(f"Context: {note}")
    prose = "\n\n".join(parts)

    from api.services import planner

    try:
        proposed = planner.replan(
            user_ctx=user_ctx,
            target_date=date.today(),
            candidate_tasks=candidate_tasks,
            prose=prose,
            previous_proposal=body.previous_proposal,
        )
    except RuntimeError as exc:
        surface_todoist_auth_failure(exc)

    return proposed


@router.post("/replan/confirm")
def replan_confirm(body: ReplanConfirmRequest, background_tasks: BackgroundTasks, user: dict = Depends(require_beta_access)) -> dict:
    """Commit the proposed afternoon schedule to GCal + Todoist."""
    user_id: str = user["sub"]

    user_ctx = _load_user_context(user_id)
    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    write_cal_id = config.get("write_calendar_id", "primary")
    tz = ZoneInfo(tz_str)

    # Idempotency guard: if today's most-recent confirmed row is itself a
    # replan-confirm within the window, this is a UI double-click — no-op
    # and replay the previous result. A non-replan recent row (i.e. a fresh
    # plan-confirm) is allowed to flow through, since the user might
    # legitimately replan immediately after confirming.
    today_row = _load_today_schedule(user_id)
    if today_row and today_row.get("replan_trigger") == "mid_day_replan" \
            and _is_within_idempotency_window(today_row.get("confirmed_at")):
        try:
            existing_ids = json.loads(today_row.get("gcal_event_ids") or "[]")
        except (json.JSONDecodeError, TypeError):
            existing_ids = []
        return {
            "confirmed": True,
            "gcal_events_created": len(existing_ids),
            "todoist_updated": 0,
            "schedule_log_id": today_row.get("id"),
        }

    todoist_client = TodoistClient(user_ctx["todoist_api_key"])

    # Push "tomorrow" tasks
    for tid in body.tomorrow_task_ids:
        try:
            todoist_client.clear_task_due(tid)
            todoist_client.add_comment(tid, "Pushed: Moved to tomorrow during mid-day replan")
        except Exception as exc:
            print(f"[replan/confirm] push_task failed for {tid}: {exc}")

    # today_row already loaded above for the idempotency guard — reuse it
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
    insert_result = supabase.from_("schedule_log").insert({
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
    new_log_id = (insert_result.data or [{}])[0].get("id")

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
        "schedule_log_id": new_log_id,
    }


@router.post("/replan/preflight")
def replan_preflight(body: ReplanPreflightRequest, user: dict = Depends(require_beta_access)) -> dict:
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
