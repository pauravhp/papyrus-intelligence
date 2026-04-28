"""Aggregates per-day stats and generates a queue-completion narrative."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

import anthropic
from pydantic import BaseModel

from api.config import settings

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class DayStatRow(BaseModel):
    schedule_date: str
    weekday: str
    tasks_completed: int
    tasks_total: int
    rhythms_completed: int
    rhythms_total: int


def compute_per_day_stats(
    user_id: str,
    schedule_dates: list[str],
    supabase,
) -> list[dict]:
    """Returns one stat row per date, in input order."""
    if not schedule_dates:
        return []

    th = (
        supabase.from_("task_history")
        .select("schedule_date, task_id, completed_at")
        .eq("user_id", user_id)
        .in_("schedule_date", schedule_dates)
        .execute()
    )
    th_rows = th.data or []

    rc = (
        supabase.from_("rhythm_completions")
        .select("completed_on, rhythm_id")
        .eq("user_id", user_id)
        .in_("completed_on", schedule_dates)
        .execute()
    )
    rc_rows = rc.data or []

    rhythms = (
        supabase.from_("rhythms")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    rhythms_total = len(rhythms.data or [])

    out: list[dict] = []
    for d in schedule_dates:
        tasks_for_day = [r for r in th_rows if r["schedule_date"] == d]
        tasks_total = len(tasks_for_day)
        tasks_completed = sum(1 for r in tasks_for_day if r.get("completed_at"))

        rhythm_keys = {r["rhythm_id"] for r in rc_rows if r["completed_on"] == d}
        rhythms_completed = len(rhythm_keys)

        weekday = WEEKDAY_NAMES[date.fromisoformat(d).weekday()]

        out.append({
            "schedule_date": d,
            "weekday": weekday,
            "tasks_completed": tasks_completed,
            "tasks_total": tasks_total,
            "rhythms_completed": rhythms_completed,
            "rhythms_total": rhythms_total,
        })
    return out


def compute_task_detail(
    user_id: str,
    schedule_dates: list[str],
    supabase,
) -> dict[str, dict]:
    """Side-load completed and incomplete task names per date for the LLM prompt."""
    if not schedule_dates:
        return {}
    th = (
        supabase.from_("task_history")
        .select("schedule_date, task_name, completed_at, incomplete_reason")
        .eq("user_id", user_id)
        .in_("schedule_date", schedule_dates)
        .execute()
    )
    out: dict[str, dict] = {d: {"completed": [], "incomplete": []} for d in schedule_dates}
    for r in (th.data or []):
        d = r["schedule_date"]
        if d not in out:
            continue
        if r.get("completed_at"):
            out[d]["completed"].append(r["task_name"])
        else:
            out[d]["incomplete"].append((r["task_name"], r.get("incomplete_reason") or "unspecified"))
    return out


def _format_date_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAY_NAMES[d.weekday()]} {MONTH_NAMES[d.month - 1]} {d.day}"


def build_aggregate_prompt(per_day: list[dict], task_detail: dict[str, dict]) -> str:
    n = len(per_day)
    instruction = (
        "a single sentence (max 25 words)"
        if n == 1
        else "a short paragraph (max 50 words, max 3 sentences)"
    )

    blocks: list[str] = []
    for row in per_day:
        d = row["schedule_date"]
        label = _format_date_label(d)
        detail = task_detail.get(d, {"completed": [], "incomplete": []})
        completed_line = (
            "Completed: " + (", ".join(detail["completed"]) if detail["completed"] else "—")
        )
        incomplete_pairs = detail["incomplete"]
        incomplete_line = (
            "Incomplete: " + (
                ", ".join(f"{name} ({reason})" for name, reason in incomplete_pairs)
                if incomplete_pairs else "—"
            )
        )
        rhythm_line = f"Rhythms kept: {row['rhythms_completed']} of {row['rhythms_total']}"
        blocks.append(f"{label}:\n  {completed_line}\n  {incomplete_line}\n  {rhythm_line}")

    per_day_block = "\n\n".join(blocks)

    return (
        "You are a calm, honest scheduling coach. Given this user's data from "
        f"the day(s) they just reviewed, write {instruction} that is warm, "
        "specific, and forward-looking. Reference concrete things — what they "
        "completed, what they pushed, the shape of the days — not generic "
        "encouragement.\n\n"
        'Never use hollow praise. Never use the word "great". Never start with '
        '"Last week," or "You". Never use bullet points or headers.\n\n'
        f"Days reviewed:\n{per_day_block}\n\n"
        "Output ONLY the prose. No markdown."
    )
