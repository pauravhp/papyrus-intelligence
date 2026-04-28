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
