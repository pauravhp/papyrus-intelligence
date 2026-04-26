"""
Coaching nudge evaluation service.

Public interface:
    get_eligible(user_ctx, messages) -> NudgeCard | None

Only runs on the first message of a conversation (len(messages) == 1).
All I/O is in _compute_signals; all other functions are pure.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# ── Catalog ───────────────────────────────────────────────────────────────────

_catalog_path = Path(__file__).parent.parent.parent / "nudge_catalog.json"
NUDGE_CATALOG: list[dict] = json.loads(_catalog_path.read_text())

# ── Response model ────────────────────────────────────────────────────────────

class NudgeCard(BaseModel):
    nudge_id: str
    coach_message: str
    learn_more_path: str
    action_label: str | None
    instance_key: str | None


# ── Public entry point ────────────────────────────────────────────────────────

def get_eligible(user_ctx: dict, messages: list[dict]) -> NudgeCard | None:
    """Return the highest-priority eligible nudge, or None."""
    # Guard: mid-conversation — zero I/O
    if len(messages) > 1:
        return None

    nudge_config = user_ctx.get("config", {}).get("nudges", {})
    if not nudge_config.get("coaching_enabled", True):
        return None

    disabled_types: list[str] = nudge_config.get("disabled_types", [])

    signals = _compute_signals(user_ctx)

    best = _select_nudge(signals, disabled_types)
    if best is None:
        return None

    # Per-dismissal check (uses pre-fetched dismissed_set from signals)
    if _is_dismissed(user_ctx["user_id"], best, signals):
        return None

    return _build_nudge_card(best, signals)


# ── Selection ─────────────────────────────────────────────────────────────────

def _select_nudge(signals: dict, disabled_types: list[str]) -> dict | None:
    """
    Evaluate all catalog entries, filter disabled/dismissed, return highest priority.
    Positive nudges (category='positive') are suppressed if any warning is eligible.
    """
    warning_candidates: list[dict] = []
    positive_candidates: list[dict] = []

    for nudge in NUDGE_CATALOG:
        if nudge["nudge_id"] in disabled_types:
            continue
        if not _condition_met(nudge, signals):
            continue
        dismissed_set: set = signals.get("dismissed_set", set())
        instance_key = _instance_key_for(nudge, signals)
        if (nudge["nudge_id"], instance_key) in dismissed_set:
            continue
        if (nudge["nudge_id"], "__type__") in dismissed_set:
            continue
        if nudge["category"] == "positive":
            positive_candidates.append(nudge)
        else:
            warning_candidates.append(nudge)

    if warning_candidates:
        return sorted(warning_candidates, key=lambda n: n["priority"])[0]
    if positive_candidates:
        return sorted(positive_candidates, key=lambda n: n["priority"])[0]
    return None


# ── Condition evaluation ──────────────────────────────────────────────────────

_OPS = {
    ">=": lambda a, b: a >= b,
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

def _condition_met(nudge: dict, signals: dict) -> bool:
    t = nudge["trigger"]
    primary_signal = signals.get(t["signal"])

    # Handle null threshold — e.g. habit_skipped checks != null
    if t["threshold"] is None:
        op = _OPS.get(t["operator"], lambda a, b: False)
        result = op(primary_signal, None)
    else:
        if primary_signal is None:
            return False
        op = _OPS.get(t["operator"], lambda a, b: False)
        result = op(primary_signal, t["threshold"])

    if not result:
        return False

    # Optional secondary condition (AND logic)
    if "secondary_signal" in t:
        sec_val = signals.get(t["secondary_signal"])
        if sec_val is None:
            return False
        sec_op = _OPS.get(t["secondary_operator"], lambda a, b: False)
        if not sec_op(sec_val, t["secondary_threshold"]):
            return False

    # Special rule: backlog_growing also requires overdue_count > 5
    if nudge["nudge_id"] == "backlog_growing":
        if signals.get("overdue_count", 0) <= 5:
            return False

    return True


# ── Dismissal check ───────────────────────────────────────────────────────────

def _is_dismissed(user_id: str, nudge: dict, signals: dict) -> bool:
    """Check pre-fetched dismissed_set — no I/O."""
    dismissed_set: set = signals.get("dismissed_set", set())
    instance_key = _instance_key_for(nudge, signals)
    if (nudge["nudge_id"], instance_key) in dismissed_set:
        return True
    if (nudge["nudge_id"], "__type__") in dismissed_set:
        return True
    return False


def _instance_key_for(nudge: dict, signals: dict) -> str | None:
    """Return the instance_key relevant for this nudge type (e.g. task_id)."""
    nudge_id = nudge["nudge_id"]
    if nudge_id == "repeated_deferral":
        return signals.get("most_pushed_task_id")
    if nudge_id == "no_deadline":
        return signals.get("tasks_without_deadline_first_id")
    if nudge_id == "waiting_task_stale":
        return signals.get("stale_waiting_task_id")
    if nudge_id == "habit_skipped":
        return signals.get("habit_skipped_rhythm_id")
    return None


# ── Card construction ─────────────────────────────────────────────────────────

def _build_nudge_card(nudge: dict, signals: dict) -> NudgeCard:
    """Render the coach_message_template with signal values."""
    nudge_id = nudge["nudge_id"]
    template: str = nudge["coach_message_template"]

    substitutions: dict[str, str] = {}

    if nudge_id == "repeated_deferral":
        substitutions = {
            "task_name": signals.get("most_pushed_task_name") or "this task",
            "push_count": str(signals.get("most_pushed_task_count", 3)),
        }
    elif nudge_id == "no_deadline":
        substitutions = {
            "task_name": signals.get("tasks_without_deadline_first_name") or "this task",
        }
    elif nudge_id == "over_scheduling":
        rate = signals.get("completion_rate_7d", 0.5)
        substitutions = {"completion_pct": str(int(rate * 100))}
    elif nudge_id == "habit_skipped":
        substitutions = {"habit_name": signals.get("habit_skipped_rhythm_name") or "this habit"}
    elif nudge_id == "waiting_task_stale":
        substitutions = {
            "task_name": signals.get("stale_waiting_task_name") or "this task",
            "days": str(signals.get("stale_waiting_task_days", 7)),
        }
    elif nudge_id == "backlog_growing":
        substitutions = {"delta": str(signals.get("backlog_delta", 0))}
    elif nudge_id == "no_breaks_scheduled":
        hours = signals.get("hours_scheduled_today", 4.0)
        substitutions = {"hours": f"{hours:.1f}"}
    elif nudge_id == "good_estimation":
        acc = signals.get("estimation_accuracy_7d", 0.85)
        substitutions = {"accuracy_pct": str(int(acc * 100))}
    elif nudge_id == "completion_streak":
        substitutions = {"streak": str(signals.get("daily_completion_streak", 3))}

    message = template
    for key, val in substitutions.items():
        message = message.replace("{" + key + "}", val)

    return NudgeCard(
        nudge_id=nudge_id,
        coach_message=message,
        learn_more_path=nudge["learn_more_path"],
        action_label=nudge.get("action_label"),
        instance_key=_instance_key_for(nudge, signals),
    )


# ── Signal computation (all I/O here) ─────────────────────────────────────────

def _compute_signals(user_ctx: dict) -> dict:
    """
    Fetch all data needed for nudge evaluation.
    Returns a flat dict of signal values.
    Gracefully defaults on missing data — never raises.
    """
    from api.db import supabase as _supabase

    user_id = user_ctx["user_id"]
    todoist_api_key = user_ctx.get("todoist_api_key")
    today = date.today()
    today_str = today.isoformat()
    two_weeks_ago = (today - timedelta(days=14)).isoformat()
    seven_days_ago = (today - timedelta(days=7)).isoformat()

    signals: dict[str, Any] = {}

    # ── schedule_log (14d) ────────────────────────────────────────
    try:
        log_rows = (
            _supabase.from_("schedule_log")
            .select("schedule_date, proposed_json, confirmed, confirmed_at")
            .eq("user_id", user_id)
            .gte("schedule_date", two_weeks_ago)
            .execute()
        ).data or []
    except Exception:
        log_rows = []

    # Push counts from proposed_json pushed arrays
    push_counts: dict[str, int] = {}
    task_names: dict[str, str] = {}
    for row in log_rows:
        try:
            proposed = json.loads(row.get("proposed_json") or "{}")
            for item in proposed.get("pushed") or []:
                tid = item.get("task_id")
                if tid:
                    push_counts[tid] = push_counts.get(tid, 0) + 1
                    if item.get("task_name"):
                        task_names[tid] = item["task_name"]
        except Exception:
            continue

    signals["push_count_by_task_id"] = push_counts
    signals["task_map"] = task_names

    if push_counts:
        top_id = max(push_counts, key=lambda k: push_counts[k])
        signals["most_pushed_task_id"] = top_id
        signals["most_pushed_task_name"] = task_names.get(top_id)
        signals["most_pushed_task_count"] = push_counts[top_id]
    else:
        signals["most_pushed_task_id"] = None
        signals["most_pushed_task_name"] = None
        signals["most_pushed_task_count"] = 0

    # Completion rate 7d (confirmed days / total planned days in last 7d)
    recent_rows = [r for r in log_rows if r.get("schedule_date", "") >= seven_days_ago]
    confirmed_days = sum(1 for r in recent_rows if r.get("confirmed"))
    signals["completion_rate_7d"] = (
        confirmed_days / len(recent_rows) if recent_rows else 1.0
    )
    signals["completed_tasks_7d"] = confirmed_days

    # Today's schedule
    today_rows = [r for r in log_rows if r.get("schedule_date") == today_str]
    today_row = today_rows[-1] if today_rows else None
    today_scheduled: list[dict] = []
    if today_row:
        try:
            proposed = json.loads(today_row.get("proposed_json") or "{}")
            today_scheduled = proposed.get("scheduled") or []
        except Exception:
            pass

    signals["task_count_today"] = len(today_scheduled)
    signals["hours_scheduled_today"] = (
        sum(item.get("duration_minutes", 0) for item in today_scheduled) / 60
    )
    signals["avg_block_duration_today_minutes"] = (
        sum(item.get("duration_minutes", 0) for item in today_scheduled) / len(today_scheduled)
        if today_scheduled else 60.0
    )
    signals["deep_work_tasks_in_trough"] = 0  # requires trough config — not yet available

    # Daily completion streak (consecutive confirmed days going back)
    streak = 0
    for i in range(1, 15):
        d = (today - timedelta(days=i)).isoformat()
        matching = [r for r in log_rows if r.get("schedule_date") == d]
        if matching and matching[-1].get("confirmed"):
            streak += 1
        else:
            break
    if today_row and today_row.get("confirmed"):
        streak += 1
    signals["daily_completion_streak"] = streak

    # Estimation accuracy — not yet tracked, defaults to ineligible
    signals["estimation_accuracy_7d"] = 0.0

    # ── nudge_dismissals ──────────────────────────────────────────
    try:
        dismissal_rows = (
            _supabase.from_("nudge_dismissals")
            .select("nudge_type, instance_key")
            .eq("user_id", user_id)
            .execute()
        ).data or []
    except Exception:
        dismissal_rows = []

    signals["dismissed_set"] = {
        (r["nudge_type"], r["instance_key"]) for r in dismissal_rows
    }

    # ── Todoist tasks ─────────────────────────────────────────────
    tasks: list[dict] = []
    if todoist_api_key:
        try:
            import httpx
            resp = httpx.get(
                "https://api.todoist.com/rest/v2/tasks",
                headers={"Authorization": f"Bearer {todoist_api_key}"},
                timeout=8,
            )
            if resp.status_code == 200:
                tasks = resp.json()
        except Exception:
            pass

    # Overdue counts
    overdue = [t for t in tasks if t.get("due") and t["due"].get("date", "") < today_str]
    overdue_7d = [t for t in tasks if t.get("due") and t["due"].get("date", "") < seven_days_ago]
    signals["overdue_count"] = len(overdue)
    signals["overdue_count_7d_ago"] = len(overdue_7d)
    signals["backlog_growth_rate"] = (
        (len(overdue) - len(overdue_7d)) / len(overdue_7d)
        if overdue_7d else 0.0
    )
    signals["backlog_delta"] = max(0, len(overdue) - len(overdue_7d))

    # Waiting tasks stale (label "@waiting", due date not updated for 7+ days)
    waiting = [
        t for t in tasks
        if "@waiting" in (t.get("labels") or [])
    ]
    stale_waiting = None
    stale_days = 0
    for t in waiting:
        # Use due date as proxy for last action
        due = (t.get("due") or {}).get("date")
        if due and due < seven_days_ago:
            days_stale = (today - date.fromisoformat(due)).days
            if days_stale > stale_days:
                stale_waiting = t
                stale_days = days_stale

    signals["stale_waiting_task_id"] = stale_waiting["id"] if stale_waiting else None
    signals["stale_waiting_task_name"] = stale_waiting["content"] if stale_waiting else None
    signals["stale_waiting_task_days"] = stale_days

    # Tasks without deadline (priority >= p3 = Todoist priority >= 2, no due date)
    no_deadline_tasks = [
        t for t in tasks
        if not t.get("due") and t.get("priority", 1) >= 2
    ]
    signals["tasks_without_deadline_count"] = len(no_deadline_tasks)
    signals["tasks_without_deadline_first_name"] = (
        no_deadline_tasks[0]["content"] if no_deadline_tasks else None
    )
    signals["tasks_without_deadline_first_id"] = (
        no_deadline_tasks[0]["id"] if no_deadline_tasks else None
    )

    # habit_skipped — not yet implemented (no rhythm_completions tracking)
    signals["habit_skipped_rhythm_id"] = None
    signals["habit_skipped_rhythm_name"] = None

    return signals
