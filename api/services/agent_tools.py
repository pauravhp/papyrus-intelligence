"""
The 10 ReAct agent tools: Python implementations + Anthropic tool schemas.

Each execute_* function accepts (tool_inputs, user_ctx) where user_ctx is:
{
  user_id: str,
  config: dict,           # full users.config from Supabase
  anthropic_api_key: str | None,
  todoist_api_key: str | None,
  gcal_service: googleapiclient.Resource,
  supabase: supabase.Client,
}

TOOL_SCHEMAS is the list passed to Anthropic messages.create(tools=...).
9 tools total — onboard_scan/apply/confirm handled by /api/onboard/* HTTP routes.
"""

import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

from src.calendar_client import create_event, get_events
from src.todoist_client import TodoistClient
from api.services.schedule_service import schedule_day
from src.scheduler import compute_free_windows
from api.services.rhythm_service import get_active_rhythms
from src.models import TodoistTask as _TodoistTask
from api.services.analytics import capture as _analytics_capture


def _compute_rhythm_sessions_done_this_week(supabase, user_id: str, target_date: date) -> dict[str, int]:
    """
    Count confirmed rhythm sessions between ISO-week Monday and target_date (inclusive).
    Returns {synthetic_task_id: count} e.g. {"proj_<uuid>": 2}.
    """
    # ISO week: Monday is day 0
    week_start = target_date - timedelta(days=target_date.weekday())
    try:
        rows = (
            supabase.from_("schedule_log")
            .select("schedule_date, proposed_json, confirmed")
            .eq("user_id", user_id)
            .eq("confirmed", 1)
            .gte("schedule_date", week_start.isoformat())
            .lte("schedule_date", target_date.isoformat())
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("[rhythm_priority] schedule_log query failed: %s — defaulting to 0 done", exc)
        return {}

    counts: dict[str, int] = {}
    for row in rows:
        try:
            proposed = json.loads(row.get("proposed_json") or "{}")
            for item in proposed.get("scheduled") or []:
                tid = item.get("task_id", "")
                if tid.startswith("proj_"):
                    counts[tid] = counts.get(tid, 0) + 1
        except Exception:
            continue
    return counts


def _rhythm_priority(sessions_remaining: int, target_date: date) -> int:
    """
    Map weekly-completion urgency to a Todoist priority (1–4; higher = more urgent).
    urgency = sessions_remaining / days_remaining_in_week (incl. target_date).
      urgency >= 0.8 → 4 (P1)
      0.4 <= urgency < 0.8 → 3 (P2)
      urgency < 0.4 → 2 (P3)
    """
    # Days remaining in the ISO week including target_date itself (1–7).
    days_remaining = 7 - target_date.weekday()
    urgency = sessions_remaining / max(1, days_remaining)
    if urgency >= 0.8:
        return 4
    if urgency >= 0.4:
        return 3
    return 2


# ── Python implementations ─────────────────────────────────────────────────────


def execute_get_date(offset_days: int, _user_ctx: dict) -> dict:
    """Return the date for today + offset_days as YYYY-MM-DD and a human label."""
    target = date.today() + timedelta(days=offset_days)
    labels = {0: "today", 1: "tomorrow", -1: "yesterday"}
    label = labels.get(offset_days, target.strftime("%A"))
    return {
        "date": target.isoformat(),
        "label": label,
        "day_of_week": target.strftime("%A"),
    }


def execute_get_tasks(filter_str: str, user_ctx: dict) -> list[dict]:
    """Fetch Todoist tasks. Returns list of task dicts."""
    client = TodoistClient(user_ctx["todoist_api_key"])
    tasks = client.get_tasks(filter_str)
    return [
        {
            "id": t.id,
            "content": t.content,
            "priority": t.priority,
            "duration_minutes": t.duration_minutes,
            "labels": t.labels,
            "due_datetime": t.due_datetime.isoformat() if t.due_datetime else None,
            "deadline": t.deadline,
            "is_inbox": t.is_inbox,
        }
        for t in tasks
    ]


def execute_get_calendar(target_date_str: str, user_ctx: dict) -> list[dict]:
    """Fetch GCal events for a given date (YYYY-MM-DD)."""
    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    cal_ids = (
        config.get("source_calendar_ids")
        or config.get("calendar_ids")
        or ["primary"]
    )
    target_date = date.fromisoformat(target_date_str)
    events = get_events(
        target_date=target_date,
        timezone_str=tz_str,
        calendar_ids=cal_ids,
        service=user_ctx["gcal_service"],
    )
    return [
        {
            "id": e.id,
            "summary": e.summary,
            "start": e.start.isoformat(),
            "end": e.end.isoformat(),
            "is_all_day": e.is_all_day,
            "color_id": e.color_id,
        }
        for e in events
    ]


def execute_schedule_day(
    context_note: str,
    target_date_str: str,
    user_ctx: dict,
) -> dict:
    """
    Inner LLM call: compute free windows then call schedule_day().
    Returns {scheduled, pushed, reasoning_summary, free_windows_used}.
    """
    config = user_ctx["config"]

    # Inject default meal blocks if the user's config has none.
    # These become hard blocked windows in compute_free_windows AND
    # are surfaced in the scheduling prompt so the LLM respects them.
    DEFAULT_MEAL_BLOCKS = [
        {"name": "Lunch",  "start": "12:30", "end": "13:30", "days": "all", "movable": False, "buffer_before_minutes": 0, "buffer_after_minutes": 0},
        {"name": "Dinner", "start": "19:00", "end": "20:00", "days": "all", "movable": False, "buffer_before_minutes": 0, "buffer_after_minutes": 0},
    ]
    if not config.get("daily_blocks"):
        config = {**config, "daily_blocks": DEFAULT_MEAL_BLOCKS}

    tz_str = config.get("user", {}).get("timezone", "UTC")
    cal_ids = (
        config.get("source_calendar_ids")
        or config.get("calendar_ids")
        or ["primary"]
    )
    target_date = date.fromisoformat(target_date_str)

    todoist_client = TodoistClient(user_ctx["todoist_api_key"])
    # Use 'tomorrow' filter when scheduling tomorrow, otherwise 'today | overdue'
    today = date.today()
    task_filter = "tomorrow" if target_date > today else "today | overdue"
    all_tasks = todoist_client.get_tasks(task_filter)
    # Full name lookup — keyed before filtering so pushed tasks can also be resolved
    task_names: dict[str, str] = {t.id: t.content for t in all_tasks}
    # Only schedulable tasks (have a duration label) go to the LLM.
    tasks_raw = [t for t in all_tasks if t.duration_minutes is not None]
    # Inject active rhythms as synthetic schedulable tasks (sorted by sort_order asc).
    # Priority is derived from weekly completion pressure so 3x/week rhythms that
    # haven't run yet by Thursday outrank P3 one-offs, while a daily rhythm with
    # all sessions already done this week is skipped entirely.
    active_rhythms = get_active_rhythms(user_ctx["user_id"], user_ctx["supabase"])
    sessions_done_by_rhythm = _compute_rhythm_sessions_done_this_week(
        user_ctx["supabase"], user_ctx["user_id"], target_date
    )
    synthetic_rhythms = []
    for rhythm in active_rhythms:
        sessions_per_week = int(rhythm["sessions_per_week"])
        sessions_done = sessions_done_by_rhythm.get(f"proj_{rhythm['id']}", 0)
        sessions_remaining = max(0, sessions_per_week - sessions_done)
        if sessions_remaining == 0:
            # Quota hit — don't inject for this week.
            continue
        synthetic = _TodoistTask(
            id=f"proj_{rhythm['id']}",
            content=(
                f"{rhythm['rhythm_name']}: {rhythm['description']}"
                if rhythm.get("description")
                else rhythm["rhythm_name"]
            ),
            project_id="rhythm",
            priority=_rhythm_priority(sessions_remaining, target_date),
            due_datetime=None,
            deadline=None,
            duration_minutes=int(rhythm["session_min_minutes"]),
            labels=[],
            is_inbox=False,
            is_rhythm=True,
            session_max_minutes=int(rhythm["session_max_minutes"]),
            sessions_per_week=sessions_per_week,
        )
        task_names[f"proj_{rhythm['id']}"] = (
            f"{rhythm['rhythm_name']}: {rhythm['description']}"
            if rhythm.get("description")
            else rhythm["rhythm_name"]
        )
        synthetic_rhythms.append(synthetic)
    tasks_raw = synthetic_rhythms + tasks_raw
    events = get_events(
        target_date=target_date,
        timezone_str=tz_str,
        calendar_ids=cal_ids,
        service=user_ctx["gcal_service"],
    )
    logger.info("[schedule_day] gcal_service=%s cal_ids=%s tz=%s events=%d",
                "SET" if user_ctx["gcal_service"] else "NONE", cal_ids, tz_str, len(events))

    scheduled_tasks = todoist_client.get_todays_scheduled_tasks(target_date)
    free_windows = compute_free_windows(events, target_date, config, scheduled_tasks=scheduled_tasks)
    # Exclude already-scheduled tasks from LLM input — they block time via free_windows above
    already_scheduled_ids = {t.id for t in scheduled_tasks}
    tasks_raw = [t for t in tasks_raw if t.id not in already_scheduled_ids]

    result = schedule_day(
        tasks=tasks_raw,
        free_windows=free_windows,
        config=config,
        context_note=context_note,
        anthropic_api_key=user_ctx.get("anthropic_api_key"),
        target_date=target_date_str,
        events=events,
    )

    # Enforce free-window constraints on LLM output (Rule 1: code enforces).
    # Any item whose proposed slot doesn't fall within a computed free window
    # is moved to pushed — this prevents scheduling on top of GCal events.
    print(f"[schedule_day] free_windows: {[(w.start.isoformat(), w.end.isoformat()) for w in free_windows]}")
    print(f"[schedule_day] LLM scheduled {len(result.get('scheduled', []))} items, pushed {len(result.get('pushed', []))} items")
    # Hard validation: only reject items that directly conflict with a real GCal event.
    # Meal blocks, min-gap, and sleep buffers are soft guidance passed to the LLM —
    # the LLM may override them when task load or user context warrants it.
    timed_events = [e for e in (events or []) if not e.is_all_day]

    valid_scheduled = []
    overflow_pushed = []
    for item in result.get("scheduled", []):
        try:
            item_start = datetime.fromisoformat(item["start_time"])
            item_end = datetime.fromisoformat(item["end_time"])
        except (KeyError, ValueError) as e:
            print(f"[schedule_day] parse error for {item.get('task_id')}: {e} — accepting as-is")
            valid_scheduled.append(item)
            continue
        gcal_conflict = any(
            item_start < e.end and item_end > e.start
            for e in timed_events
        )
        in_window = any(
            item_start >= w.start and item_end <= w.end
            for w in free_windows
        )
        print(f"[schedule_day] {item.get('task_id')} start={item['start_time']} end={item['end_time']} in_window={in_window} gcal_conflict={gcal_conflict}")
        if gcal_conflict:
            overflow_pushed.append({
                "task_id": item.get("task_id", ""),
                "task_name": item.get("task_name") or task_names.get(item.get("task_id", ""), item.get("task_id", "")),
                "reason": "Conflicts with an existing calendar event",
            })
        else:
            valid_scheduled.append(item)
    result["scheduled"] = valid_scheduled
    result["pushed"] = list(result.get("pushed", [])) + overflow_pushed

    # Restore full task names for scheduled items (inner LLM only saw truncated versions)
    for item in result.get("scheduled", []):
        tid = item.get("task_id")
        if tid and tid in task_names:
            item["task_name"] = task_names[tid]

    # Restore full task names for pushed items
    for item in result.get("pushed", []):
        if "task_name" not in item or not item["task_name"]:
            tid = item.get("task_id", "")
            item["task_name"] = task_names.get(tid, tid)

    print(f"[schedule_day] after validation: {len(result['scheduled'])} scheduled, {len(result['pushed'])} pushed")

    result["free_windows_used"] = [
        {"start": w.start.strftime("%H:%M"), "end": w.end.strftime("%H:%M"), "duration_minutes": w.duration_minutes}
        for w in free_windows
    ]
    return result


def execute_confirm_schedule(schedule: dict, user_ctx: dict) -> dict:
    """
    Write-only tool (Rule 2): create GCal events + set Todoist due_datetimes.
    Also saves to schedule_log (confirmed=1).
    Returns {confirmed: True, gcal_events_created: int, todoist_updated: int}.
    """
    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    write_cal_id = config.get("write_calendar_id", "primary")
    todoist_client = TodoistClient(user_ctx["todoist_api_key"])
    gcal_count = 0
    todoist_count = 0
    gcal_event_ids: list[str] = []

    for item in schedule.get("scheduled", []):
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
            gcal_event_ids.append(gcal_id)
            gcal_count += 1
        except Exception as exc:
            print(f"[confirm_schedule] GCal create failed for {item.get('task_name')}: {exc}")

        # Skip Todoist write for project budget tasks — budget tracked via log_project_session
        if not item.get("task_id", "").startswith("proj_"):
            try:
                start_dt = datetime.fromisoformat(item["start_time"])
                todoist_client.schedule_task(
                    item["task_id"], start_dt, item["duration_minutes"]
                )
                todoist_count += 1
            except Exception as exc:
                print(f"[confirm_schedule] Todoist update failed for {item.get('task_id')}: {exc}")

    import json as _json
    from datetime import datetime as _dt
    user_ctx["supabase"].from_("schedule_log").insert({
        "user_id": user_ctx["user_id"],
        "run_at": _dt.now().isoformat(),
        "schedule_date": date.today().isoformat(),
        "proposed_json": _json.dumps(schedule),
        "confirmed": 1,
        "confirmed_at": _dt.now().isoformat(),
        "gcal_event_ids": _json.dumps(gcal_event_ids),
        "gcal_write_calendar_id": write_cal_id,
    }).execute()

    # Fire analytics — inline because this is not a route handler.
    # PostHog SDK is non-blocking; failure must never affect the schedule write.
    try:
        scheduled_items = schedule.get("scheduled", [])
        _analytics_capture(
            user_ctx["user_id"],
            "schedule_confirmed",
            {
                "task_count": len(scheduled_items),
                "total_duration_minutes": sum(
                    item.get("duration_minutes", 0) for item in scheduled_items
                ),
                "schedule_date": date.today().isoformat(),
            },
        )
    except Exception:
        pass

    return {
        "confirmed": True,
        "gcal_events_created": gcal_count,
        "todoist_updated": todoist_count,
    }


def execute_push_task(task_id: str, reason: str, user_ctx: dict) -> dict:
    """Clear due date from a task and add a comment explaining the push."""
    client = TodoistClient(user_ctx["todoist_api_key"])
    client.clear_task_due(task_id)
    client.add_comment(task_id, f"Pushed: {reason}")
    return {"pushed": True, "task_id": task_id}


def execute_get_status(user_ctx: dict) -> dict:
    """Return today's confirmed schedule from schedule_log."""
    today = date.today().isoformat()
    result = (
        user_ctx["supabase"]
        .from_("schedule_log")
        .select("proposed_json, confirmed_at")
        .eq("user_id", user_ctx["user_id"])
        .eq("schedule_date", today)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows or not rows[0].get("proposed_json"):
        return {"status": "no_confirmed_schedule", "schedule": None}
    import json as _json
    return {
        "status": "confirmed",
        "schedule": _json.loads(rows[0]["proposed_json"]),
        "confirmed_at": rows[0].get("confirmed_at"),
    }


def execute_onboard_apply(draft_config: dict, answers: list[dict], user_ctx: dict) -> dict:
    """Apply user answers to draft config (Stage 2 logic)."""
    import copy as _copy

    def _set_nested(d, path, value):
        keys = path.split(".")
        node = d
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                return
            node = node[key]
        leaf = keys[-1]
        if leaf in node:
            node[leaf] = value

    draft = _copy.deepcopy(draft_config)
    for answer in answers:
        val = answer.get("value", "")
        field = answer.get("field", "")
        if field.endswith("_minutes") or field.endswith("_min"):
            try:
                val = int(val)
            except (ValueError, TypeError):
                pass
        _set_nested(draft, field, val)
    return {"updated_config": draft, "answers_applied": len(answers)}


def execute_onboard_confirm(draft_config: dict, user_ctx: dict) -> dict:
    """Promote draft config to live (writes users.config in Supabase)."""
    import copy as _copy
    clean = _copy.deepcopy(draft_config)
    clean.pop("_onboard_draft", None)
    user_ctx["supabase"].from_("users").update({"config": clean}).eq("id", user_ctx["user_id"]).execute()
    return {"promoted": True}


def execute_get_rhythms(_inp: dict, user_ctx: dict) -> list[dict]:
    """Return active rhythms with session range and cadence. No LLM call."""
    return get_active_rhythms(user_ctx["user_id"], user_ctx["supabase"])


def execute_manage_rhythm(inp: dict, user_ctx: dict) -> dict:
    """
    CRUD for rhythms via natural language.
    inp.action: "create" | "update" | "delete"
    """
    from api.services.rhythm_service import (
        create_rhythm, update_rhythm, delete_rhythm,
    )
    action = inp.get("action")
    uid = user_ctx["user_id"]
    sb = user_ctx["supabase"]

    if action == "create":
        return create_rhythm(
            uid, sb,
            name=inp["name"],
            sessions_per_week=int(inp["sessions_per_week"]),
            session_min=int(inp.get("session_min", 60)),
            session_max=int(inp.get("session_max", 120)),
            end_date=inp.get("end_date"),
            sort_order=int(inp.get("sort_order", 0)),
            description=inp.get("description"),
        )
    elif action == "update":
        from api.services.rhythm_service import _DESCRIPTION_UNSET
        desc = inp["description"] if "description" in inp else _DESCRIPTION_UNSET
        return update_rhythm(
            uid, sb,
            rhythm_id=int(inp["rhythm_id"]),
            sessions_per_week=inp.get("sessions_per_week"),
            session_min=inp.get("session_min"),
            session_max=inp.get("session_max"),
            end_date=inp.get("end_date"),
            sort_order=inp.get("sort_order"),
            description=desc,
        )
    elif action == "delete":
        delete_rhythm(uid, sb, int(inp["rhythm_id"]))
        return {"deleted": True, "rhythm_id": inp["rhythm_id"]}
    else:
        return {"error": f"Unknown action: {action}"}


# ── Anthropic tool schemas ─────────────────────────────────────────────────────

TOOL_SCHEMAS = [  # onboard_scan/apply/confirm intentionally excluded — handled by /api/onboard/* HTTP routes
    {
        "name": "get_date",
        "description": "Get the calendar date for today or a relative offset. Use offset_days=0 for today, 1 for tomorrow, -1 for yesterday, 7 for next week, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offset_days": {"type": "integer", "description": "0=today, 1=tomorrow, -1=yesterday, 7=one week from today, etc."}
            },
            "required": ["offset_days"],
        },
    },
    {
        "name": "get_tasks",
        "description": "Fetch Todoist tasks. Use only when the user asks to see their task list directly. Do NOT call before schedule_day — schedule_day fetches tasks internally.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_str": {"type": "string", "description": "Todoist filter string, e.g. 'today', 'p1', 'overdue'"}
            },
            "required": ["filter_str"],
        },
    },
    {
        "name": "get_calendar",
        "description": "Fetch Google Calendar events for a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_date": {"type": "string", "description": "Date in YYYY-MM-DD format"}
            },
            "required": ["target_date"],
        },
    },
    {
        "name": "schedule_day",
        "description": "Run the scheduling LLM to assign tasks to time slots. Returns a proposed schedule. ALWAYS call this before confirm_schedule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context_note": {"type": "string", "description": "User's context, e.g. 'light day, roommate not well'"},
                "target_date": {"type": "string", "description": "Date to schedule in YYYY-MM-DD format"},
            },
            "required": ["context_note", "target_date"],
        },
    },
    {
        "name": "confirm_schedule",
        "description": "Write the proposed schedule to Google Calendar and Todoist. Only call this after the user has explicitly approved the schedule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule": {
                    "type": "object",
                    "description": "The schedule object returned by schedule_day",
                }
            },
            "required": ["schedule"],
        },
    },
    {
        "name": "push_task",
        "description": "Clear a task's due date and add a comment explaining why it was pushed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["task_id", "reason"],
        },
    },
    {
        "name": "get_status",
        "description": "Return today's confirmed schedule from the database.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_rhythms",
        "description": "Return all active rhythms with session range and cadence. Call this when the user asks about their rhythms or wants to see what recurring sessions are scheduled.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "manage_rhythm",
        "description": "Create, update, or delete a rhythm. Use when the user describes a recurring weekly commitment they want to protect time for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "delete"]},
                "rhythm_id": {"type": "integer", "description": "Required for update/delete"},
                "name": {"type": "string", "description": "Required for create"},
                "sessions_per_week": {"type": "integer", "description": "Required for create — how many sessions per week (e.g. 2)"},
                "session_min": {"type": "integer", "description": "Min session minutes (default 60)"},
                "session_max": {"type": "integer", "description": "Max session minutes (default 120)"},
                "end_date": {"type": "string", "description": "Optional ISO date e.g. 2026-08-01 — soft end, rhythm stops being injected after this"},
                "sort_order": {"type": "integer", "description": "Lower = scheduled first when multiple rhythms exist (default 0)"},
                "description": {"type": "string", "description": "One-line scheduling hint passed to the agent when planning the day (e.g. 'mornings only', 'before deep work'). Max 80 chars. Optional."},
            },
            "required": ["action"],
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────

TOOL_DISPATCH = {
    "get_date":          lambda inp, ctx: execute_get_date(inp["offset_days"], ctx),
    "get_tasks":         lambda inp, ctx: execute_get_tasks(inp["filter_str"], ctx),
    "get_calendar":      lambda inp, ctx: execute_get_calendar(inp["target_date"], ctx),
    "schedule_day":      lambda inp, ctx: execute_schedule_day(inp["context_note"], inp["target_date"], ctx),
    "confirm_schedule":  lambda inp, ctx: execute_confirm_schedule(inp["schedule"], ctx),
    "push_task":         lambda inp, ctx: execute_push_task(inp["task_id"], inp["reason"], ctx),
    "get_status":        lambda inp, ctx: execute_get_status(ctx),
    "get_rhythms":       lambda inp, ctx: execute_get_rhythms(inp, ctx),
    "manage_rhythm":     lambda inp, ctx: execute_manage_rhythm(inp, ctx),
}
