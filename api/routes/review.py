# api/routes/review.py

import json
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import get_current_user, require_beta_access
from api.db import supabase
from api.services.analytics import capture
from api.services.review_aggregate_service import (
    DayStatRow,
    compute_per_day_stats,
    compute_task_detail,
    generate_aggregate_narrative,
)
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
    schedule_date: str | None = None
    tasks: list[ReviewSubmitTask]
    rhythms: list[ReviewSubmitRhythm]


def _validate_review_date(value: str | None) -> str:
    if value is None:
        return date.today().isoformat()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="schedule_date must be YYYY-MM-DD")
    today = date.today()
    if parsed > today:
        raise HTTPException(status_code=400, detail="schedule_date cannot be in the future")
    if parsed < today - timedelta(days=7):
        raise HTTPException(status_code=400, detail="schedule_date is older than the 7-day review window")
    return parsed.isoformat()


@router.get("/review/preflight")
def review_preflight(
    date_param: str | None = Query(default=None, alias="date"),
    user: dict = Depends(require_beta_access),
) -> dict:
    user_id = user["sub"]
    target_date = _validate_review_date(date_param)

    # 1. Get the most recent unreviewed confirmed schedule with non-empty
    # scheduled[] for the target date. We don't blindly take the highest-id
    # row: replan or other flows can leave behind a confirmed=1 row whose
    # proposed_json is null / "{}" / has scheduled=[]. The review queue (in
    # api/routes/today.py:_compute_review_queue) uses the SAME filters as
    # this query (confirmed=1, reviewed_at IS NULL), so if we match those
    # filters we match the queue's view of the day.
    result = (
        supabase.from_("schedule_log")
        .select("id, proposed_json")
        .eq("user_id", user_id)
        .eq("schedule_date", target_date)
        .eq("confirmed", 1)
        .is_("reviewed_at", "null")
        .order("id", desc=True)
        .execute()
    )
    rows = result.data or []
    schedule: dict | None = None
    chosen_row_id: int | None = None
    for row in rows:
        raw = row.get("proposed_json")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("scheduled"):
            schedule = parsed
            chosen_row_id = row.get("id")
            break

    if schedule is None:
        logger.warning(
            "[review.preflight] no usable schedule_log row for user=%s date=%s "
            "(rows_seen=%d, queue would have included this date)",
            user_id, target_date, len(rows),
        )
        raise HTTPException(status_code=404, detail=f"No confirmed schedule for {target_date}")

    logger.info(
        "[review.preflight] using schedule_log id=%s for user=%s date=%s",
        chosen_row_id, user_id, target_date,
    )
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

    # 3. Split scheduled[] by task_id prefix:
    #   - "proj_<rhythm_id>" → synthetic rhythm task; review via Rhythms section
    #     so the submit writes rhythm_completions (not task_history).
    #   - Anything else → real Todoist task; review via Tasks section.
    # No days_of_week filter — if the user (or an LLM refinement) put a rhythm
    # onto an off-day, it's still in scheduled[] and still reviewable here.
    real_tasks: list[dict] = []
    scheduled_rhythms: list[dict] = []
    for t in tasks:
        task_id = t.get("task_id") or ""
        if task_id.startswith("proj_"):
            try:
                rhythm_id = int(task_id[len("proj_"):])
            except ValueError:
                # malformed proj_ id — drop it rather than crash the modal
                logger.warning("[review.preflight] non-integer rhythm id in task_id=%s", task_id)
                continue
            scheduled_rhythms.append({
                "id": rhythm_id,
                "rhythm_name": t.get("task_name") or "(unnamed rhythm)",
            })
        else:
            real_tasks.append(t)

    return {
        "tasks": [
            {
                "task_id": t["task_id"],
                "task_name": t["task_name"],
                "estimated_duration_mins": t.get("duration_minutes", 30),
                "scheduled_at": t["start_time"],
                "already_completed_in_todoist": t["task_id"] in completed_ids,
            }
            for t in real_tasks
        ],
        "rhythms": scheduled_rhythms,
    }


@router.post("/review/submit")
def review_submit(body: ReviewSubmitRequest, background_tasks: BackgroundTasks, user: dict = Depends(require_beta_access)) -> dict:
    user_id = user["sub"]
    target_date = _validate_review_date(body.schedule_date)

    # 1. Upsert task_history rows
    task_rows = [
        {
            "user_id": user_id,
            "task_id": t.task_id,
            "task_name": t.task_name,
            "schedule_date": target_date,
            "estimated_duration_mins": t.estimated_duration_mins,
            "actual_duration_mins": t.actual_duration_mins if t.completed else None,
            "scheduled_at": t.scheduled_at,
            "completed_at": datetime.now(timezone.utc).isoformat() if t.completed else None,
            "incomplete_reason": t.incomplete_reason,
            # Stored as bigint (legacy SQLite-mirror schema). 1 = agent-scheduled.
            "was_agent_scheduled": 1,
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
            "completed_on": target_date,
        }
        for r in body.rhythms
        if r.completed
    ]
    if rhythm_rows:
        supabase.from_("rhythm_completions").upsert(
            rhythm_rows,
            on_conflict="user_id,rhythm_id,completed_on",
            ignore_duplicates=True,
        ).execute()

    # 3. Stamp reviewed_at on the confirmed schedule_log row (idempotent — only if not already set)
    supabase.from_("schedule_log").update({
        "reviewed_at": datetime.now(timezone.utc).isoformat()
    }).eq("user_id", user_id).eq("schedule_date", target_date).eq("confirmed", 1).is_("reviewed_at", "null").execute()

    background_tasks.add_task(
        capture,
        user_id,
        "review_submitted",
        {
            "tasks_total": len(body.tasks),
            "tasks_completed": sum(1 for t in body.tasks if t.completed),
            "rhythms_total": len(body.rhythms),
            "rhythms_completed": sum(1 for r in body.rhythms if r.completed),
        },
    )

    return {"saved": True}


class AggregateRequest(BaseModel):
    schedule_dates: list[str]


class AggregateResponse(BaseModel):
    narrative_line: str
    per_day: list[DayStatRow]


@router.post("/review/aggregate")
def review_aggregate(
    body: AggregateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_beta_access),
) -> AggregateResponse:
    user_id = user["sub"]

    if not body.schedule_dates:
        raise HTTPException(status_code=400, detail="schedule_dates must not be empty")
    if len(body.schedule_dates) > 7:
        raise HTTPException(status_code=400, detail="schedule_dates length must be <= 7")
    for d in body.schedule_dates:
        _validate_review_date(d)

    per_day = compute_per_day_stats(user_id, body.schedule_dates, supabase)
    task_detail = compute_task_detail(user_id, body.schedule_dates, supabase)
    narrative = generate_aggregate_narrative(per_day, task_detail)

    total_tasks_completed = sum(p["tasks_completed"] for p in per_day)
    total_tasks_total = sum(p["tasks_total"] for p in per_day)
    background_tasks.add_task(
        capture,
        user_id,
        "review_queue_completed",
        {
            "days_submitted": len(per_day),
            "total_tasks_completed": total_tasks_completed,
            "total_tasks_total": total_tasks_total,
        },
    )

    return AggregateResponse(narrative_line=narrative, per_day=[DayStatRow(**p) for p in per_day])

