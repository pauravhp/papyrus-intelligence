# api/routes/review.py

import json
import logging
from datetime import date

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.config import settings
from api.db import supabase
from src.todoist_client import TodoistClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class ReviewPreflightTask(BaseModel):
    task_id: str
    task_name: str
    estimated_duration_mins: int
    scheduled_at: str
    already_completed_in_todoist: bool


class ReviewPreflightRhythm(BaseModel):
    id: int
    rhythm_name: str


class ReviewPreflightResponse(BaseModel):
    tasks: list[ReviewPreflightTask]
    rhythms: list[ReviewPreflightRhythm]


class ReviewSubmitTask(BaseModel):
    task_id: str
    task_name: str
    completed: bool
    actual_duration_mins: int | None = None
    estimated_duration_mins: int
    scheduled_at: str
    incomplete_reason: str | None = None


class ReviewSubmitRhythm(BaseModel):
    rhythm_id: int
    completed: bool


class ReviewSubmitRequest(BaseModel):
    tasks: list[ReviewSubmitTask]
    rhythms: list[ReviewSubmitRhythm]


@router.get("/review/preflight")
def review_preflight(user: dict = Depends(get_current_user)) -> dict:
    user_id = user["sub"]
    today = date.today().isoformat()

    # 1. Get today's confirmed schedule
    result = (
        supabase.from_("schedule_log")
        .select("proposed_json")
        .eq("user_id", user_id)
        .eq("schedule_date", today)
        .eq("confirmed", 1)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows or not rows[0].get("proposed_json"):
        raise HTTPException(status_code=404, detail="No confirmed schedule for today")

    schedule = json.loads(rows[0]["proposed_json"])
    tasks = schedule.get("scheduled", [])

    # 2. Check Todoist for completed task IDs (swallow any failures)
    completed_ids: set[str] = set()
    try:
        user_row = (
            supabase.from_("users")
            .select("todoist_oauth_token")
            .eq("id", user_id)
            .single()
            .execute()
        )
        user_data = user_row.data or {}
        todoist_token = (user_data.get("todoist_oauth_token") or {}).get("access_token")
        if todoist_token:
            todoist = TodoistClient(todoist_token)
            for t in tasks:
                try:
                    task_result = todoist.get_task(t["task_id"])
                    if task_result is None:
                        completed_ids.add(t["task_id"])
                except Exception:
                    pass
    except Exception:
        logger.warning("Todoist preflight failed, defaulting all tasks to incomplete")

    # 3. Get active rhythms
    rhythms_result = (
        supabase.from_("rhythms")
        .select("id, rhythm_name")
        .eq("user_id", user_id)
        .execute()
    )
    rhythms = rhythms_result.data or []

    return {
        "tasks": [
            {
                "task_id": t["task_id"],
                "task_name": t["task_name"],
                "estimated_duration_mins": t.get("duration_minutes", 30),
                "scheduled_at": t["start_time"],
                "already_completed_in_todoist": t["task_id"] in completed_ids,
            }
            for t in tasks
        ],
        "rhythms": rhythms,
    }


def _generate_summary_line(user: dict, tasks: list[ReviewSubmitTask], rhythms: list[ReviewSubmitRhythm]) -> str:
    """Single LLM call to generate a one-line contextual observation."""
    completed = [t for t in tasks if t.completed]
    incomplete = [t for t in tasks if not t.completed]
    rhythms_done = [r for r in rhythms if r.completed]

    summary_input = {
        "tasks_completed": [t.task_name for t in completed],
        "tasks_incomplete": [
            {"name": t.task_name, "reason": t.incomplete_reason}
            for t in incomplete
        ],
        "rhythms_kept": len(rhythms_done),
        "rhythms_total": len(rhythms),
    }

    prompt = (
        "You are a calm, honest scheduling coach. "
        "Given this end-of-day summary, write a single sentence (max 15 words) "
        "that is warm, forward-looking, and specific to what actually happened. "
        "Never use hollow praise. Never use the word 'great'. "
        f"Summary: {json.dumps(summary_input)}"
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=60,
        temperature=0.4,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


@router.post("/review/submit")
def review_submit(body: ReviewSubmitRequest, user: dict = Depends(get_current_user)) -> dict:
    user_id = user["sub"]
    today = date.today().isoformat()

    completed_count = sum(1 for t in body.tasks if t.completed)
    total_count = len(body.tasks)

    # 1. Upsert task_history rows
    task_rows = [
        {
            "user_id": user_id,
            "task_id": t.task_id,
            "task_name": t.task_name,
            "schedule_date": today,
            "estimated_duration_mins": t.estimated_duration_mins,
            "actual_duration_mins": t.actual_duration_mins if t.completed else None,
            "scheduled_at": t.scheduled_at,
            "completed_at": today if t.completed else None,
            "incomplete_reason": t.incomplete_reason,
            "was_agent_scheduled": True,
            "sync_source": "review_ui",
        }
        for t in body.tasks
    ]
    if task_rows:
        supabase.from_("task_history").upsert(
            task_rows,
            on_conflict="user_id,task_id,schedule_date"
        ).execute()

    # 2. Insert rhythm_completions for completed rhythms (ignore on conflict)
    rhythm_rows = [
        {
            "user_id": user_id,
            "rhythm_id": r.rhythm_id,
            "completed_on": today,
        }
        for r in body.rhythms
        if r.completed
    ]
    if rhythm_rows:
        supabase.from_("rhythm_completions").insert(rhythm_rows).execute()

    # 3. Generate summary line (graceful fallback)
    try:
        summary_line = _generate_summary_line(user, body.tasks, body.rhythms)
    except Exception:
        logger.warning("LLM summary generation failed, using fallback")
        summary_line = f"{completed_count} of {total_count} tasks done."

    return {"saved": True, "summary_line": summary_line}

