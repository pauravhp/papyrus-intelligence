"""
The 10 ReAct agent tools: Python implementations + Anthropic tool schemas.

Each execute_* function accepts (tool_inputs, user_ctx) where user_ctx is:
{
  user_id: str,
  config: dict,           # full users.config from Supabase
  anthropic_api_key: str | None,
  groq_api_key: str | None,
  todoist_api_key: str | None,
  gcal_service: googleapiclient.Resource,
  supabase: supabase.Client,
}

TOOL_SCHEMAS is the list passed to Anthropic messages.create(tools=...).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.calendar_client import create_event, get_events
from src.todoist_client import TodoistClient
from api.services.schedule_service import schedule_day
from src.scheduler import compute_free_windows


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
    cal_ids = config.get("calendar_ids", [])
    target_date = date.fromisoformat(target_date_str)
    events = get_events(
        target_date=target_date,
        timezone_str=tz_str,
        extra_calendar_ids=cal_ids,
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
    tz_str = config.get("user", {}).get("timezone", "UTC")
    cal_ids = config.get("calendar_ids", [])
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
    events = get_events(
        target_date=target_date,
        timezone_str=tz_str,
        extra_calendar_ids=cal_ids,
        service=user_ctx["gcal_service"],
    )

    scheduled_tasks = todoist_client.get_todays_scheduled_tasks(target_date)
    free_windows = compute_free_windows(events, target_date, config, scheduled_tasks)

    result = schedule_day(
        tasks=tasks_raw,
        free_windows=free_windows,
        config=config,
        context_note=context_note,
        anthropic_api_key=user_ctx.get("anthropic_api_key"),
        groq_api_key=user_ctx.get("groq_api_key"),
        target_date=target_date_str,
    )
    # Restore full task names (inner LLM only saw truncated versions)
    for item in result.get("scheduled", []):
        tid = item.get("task_id")
        if tid and tid in task_names:
            item["task_name"] = task_names[tid]

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
            )
            gcal_event_ids.append(gcal_id)
            gcal_count += 1
        except Exception as exc:
            print(f"[confirm_schedule] GCal create failed for {item.get('task_name')}: {exc}")

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
    }).execute()

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


def execute_onboard_scan(timezone: str, calendar_ids: list, groq_api_key: str, user_ctx: dict) -> dict:
    """Re-run onboard Stage 1 scan (14-day GCal analysis → proposed config)."""
    from datetime import timedelta
    from src.onboard_patterns import build_pattern_summary
    from src.prompts.onboard import build_onboard_prompt
    from src.llm import _groq_json_call
    from pathlib import Path
    import json as _json
    from groq import Groq

    today = date.today()
    start_date = today - timedelta(days=13)
    events_by_date: dict = {}
    all_events = []

    for i in range(14):
        target = start_date + timedelta(days=i)
        try:
            day_events = get_events(
                target_date=target,
                timezone_str=timezone,
                extra_calendar_ids=calendar_ids,
                service=user_ctx["gcal_service"],
            )
            events_by_date[target] = day_events
            all_events.extend(day_events)
        except Exception:
            events_by_date[target] = []

    template_path = Path(__file__).parent.parent.parent / "context.template.json"
    with open(template_path) as f:
        template = _json.load(f)

    context_for_prompt = {"user": {"timezone": timezone}, "calendar_ids": calendar_ids,
                          **{k: v for k, v in template.items() if k not in ("user", "calendar_ids")}}

    patterns = build_pattern_summary(events_by_date, all_events)
    groq_client = Groq(api_key=groq_api_key)
    messages = build_onboard_prompt(patterns, context_for_prompt)
    raw = _groq_json_call(groq_client, "meta-llama/llama-4-scout-17b-16e-instruct", messages, "onboard_scan")
    return {
        "proposed_config": raw.get("proposed_config", {}),
        "questions_for_stage_2": raw.get("questions_for_stage_2", []),
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


def execute_get_projects(_inp: dict, user_ctx: dict) -> list[dict]:
    """Return active project budgets with deadline pressure. No LLM call."""
    from api.services.project_service import get_active_projects
    return get_active_projects(user_ctx["user_id"], user_ctx["supabase"])


def execute_log_project_session(inp: dict, user_ctx: dict) -> dict:
    """
    Manually decrement a project budget after actual work.
    This is the ONLY budget decay path — confirm_schedule does not auto-decrement.
    inp: {project_id: int, hours_worked: float}
    """
    from api.services.project_service import log_session
    return log_session(
        user_ctx["user_id"],
        user_ctx["supabase"],
        project_id=int(inp["project_id"]),
        hours_worked=float(inp["hours_worked"]),
    )


def execute_manage_project(inp: dict, user_ctx: dict) -> dict:
    """
    CRUD for project budgets via natural language.
    inp.action: "create" | "update" | "delete" | "reset"
    """
    from api.services.project_service import (
        create_project, update_project, delete_project, reset_project,
    )
    action = inp.get("action")
    uid = user_ctx["user_id"]
    sb = user_ctx["supabase"]

    if action == "create":
        return create_project(
            uid, sb,
            name=inp["name"],
            total_hours=float(inp["total_hours"]),
            session_min=int(inp.get("session_min", 60)),
            session_max=int(inp.get("session_max", 180)),
            deadline=inp.get("deadline"),
            priority=int(inp.get("priority", 3)),
        )
    elif action == "update":
        return update_project(
            uid, sb,
            project_id=int(inp["project_id"]),
            session_min=inp.get("session_min"),
            session_max=inp.get("session_max"),
            deadline=inp.get("deadline"),
            priority=inp.get("priority"),
            add_hours=inp.get("add_hours"),
        )
    elif action == "delete":
        delete_project(uid, sb, int(inp["project_id"]))
        return {"deleted": True, "project_id": inp["project_id"]}
    elif action == "reset":
        return reset_project(uid, sb, int(inp["project_id"]))
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
        "name": "get_projects",
        "description": "Return all active project budgets with remaining hours and deadline pressure. Call this when scheduling to include project sessions automatically.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "log_project_session",
        "description": "Manually log hours worked on a project, decrementing its budget. Call this when the user reports time spent on a project (e.g. 'I worked 1.5h on the App project today').",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "The project id from get_projects"},
                "hours_worked": {"type": "number", "description": "Hours actually worked (e.g. 1.5)"},
            },
            "required": ["project_id", "hours_worked"],
        },
    },
    {
        "name": "manage_project",
        "description": "Create, update, delete, or reset a project budget via natural language.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "delete", "reset"]},
                "project_id": {"type": "integer", "description": "Required for update/delete/reset"},
                "name": {"type": "string", "description": "Required for create"},
                "total_hours": {"type": "number", "description": "Required for create"},
                "session_min": {"type": "integer", "description": "Min session minutes (default 60)"},
                "session_max": {"type": "integer", "description": "Max session minutes (default 180)"},
                "deadline": {"type": "string", "description": "ISO date e.g. 2026-05-01"},
                "priority": {"type": "integer", "description": "4=P1, 3=P2, 2=P3, 1=P4"},
                "add_hours": {"type": "number", "description": "Add hours to remaining (update only)"},
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
    "get_projects":          lambda inp, ctx: execute_get_projects(inp, ctx),
    "log_project_session":   lambda inp, ctx: execute_log_project_session(inp, ctx),
    "manage_project":        lambda inp, ctx: execute_manage_project(inp, ctx),
}
