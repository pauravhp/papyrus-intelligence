"""
POST /api/plan-day

Authenticated. Runs the full scheduling pipeline for a given date and returns
the proposed schedule JSON. No Todoist write-back — that comes in a follow-up
/api/plan-day/confirm route (not yet implemented).

Pipeline:
  GCal → Todoist → filter buckets → compute_free_windows →
  LLM Step 1 (enrich) → LLM Step 2 (schedule) → pack_schedule

Credentials:
- Todoist: OAuth access token loaded from users.todoist_oauth_token
- LLM: server-side ANTHROPIC_API_KEY from settings
- GCal: per-user OAuth credentials from users.google_credentials
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import get_current_user
from api.config import settings
from api.db import supabase
from src.calendar_client import get_events
from src.llm import _anthropic_json_call, ANTHROPIC_SCHEDULE_MODEL
from src.models import TodoistTask
from src.prompts.enrich import build_enrich_prompt
from src.prompts.schedule import build_schedule_prompt
from src.schedule_pipeline import build_enriched_task_details
from src.scheduler import compute_free_windows, pack_schedule
from src.todoist_client import TodoistClient

router = APIRouter(prefix="/api")

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}

_PROD_SCIENCE_PATH = Path(__file__).parent.parent.parent / "productivity_science.json"


def _load_prod_science() -> dict:
    try:
        with open(_PROD_SCIENCE_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="productivity_science.json not found on server",
        )


# ── Models ────────────────────────────────────────────────────────────────────


class PlanDayRequest(BaseModel):
    date: str | None = None  # YYYY-MM-DD; defaults to today


class ScheduledBlockOut(BaseModel):
    task_id: str
    task_name: str
    start_time: str   # ISO 8601
    end_time: str
    duration_minutes: int
    work_block: str
    placement_reason: str
    split_session: bool
    back_to_back: bool


class PlanDayResponse(BaseModel):
    target_date: str
    reasoning_summary: str
    scheduled: list[ScheduledBlockOut]
    pushed: list[dict]
    flagged: list[dict]
    already_scheduled: list[dict]
    skipped_count: int
    free_windows_count: int


# ── Route ─────────────────────────────────────────────────────────────────────


@router.post("/plan-day", response_model=PlanDayResponse)
def plan_day(
    body: PlanDayRequest,
    user: dict = Depends(get_current_user),
) -> PlanDayResponse:
    user_id: str = user["sub"]

    # ── Resolve target date ────────────────────────────────────────────────────
    if body.date:
        try:
            target_date = date.fromisoformat(body.date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date: {body.date}")
    else:
        target_date = date.today()

    # ── Fetch user row from Supabase ──────────────────────────────────────────
    row_result = (
        supabase.from_("users")
        .select("config, todoist_oauth_token")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if not row_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User row not found in Supabase. Complete onboarding first.",
        )

    row = row_result.data
    context: dict = row.get("config") or {}

    if not context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User config is empty. Complete onboarding (promote stage) first.",
        )

    todoist_token: str | None = (row.get("todoist_oauth_token") or {}).get("access_token")
    if not todoist_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Todoist not connected. Complete onboarding at /onboard first.",
        )
    ant_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    prod_science = _load_prod_science()
    tz_str: str = context.get("user", {}).get("timezone", "America/Vancouver")
    extra_cal_ids: list[str] = context.get("calendar_ids", [])

    # ── GCal — today + day_before for late-night detection ────────────────────
    events = []
    try:
        events = get_events(target_date, tz_str, extra_calendar_ids=extra_cal_ids)
    except Exception as exc:
        print(f"[plan-day] GCal fetch failed: {exc}")

    late_night_prior = False
    try:
        tz = ZoneInfo(tz_str)
        threshold_str = context.get("sleep", {}).get("late_night_threshold", "23:00")
        h, m = map(int, threshold_str.split(":"))
        day_before = target_date - timedelta(days=1)
        threshold_dt = datetime(day_before.year, day_before.month, day_before.day,
                                h, m, tzinfo=tz)
        for ev in get_events(day_before, tz_str, extra_calendar_ids=extra_cal_ids):
            ev_end = ev.end if ev.end.tzinfo else ev.end.replace(tzinfo=tz)
            if not ev.is_all_day and ev_end >= threshold_dt:
                late_night_prior = True
                break
    except Exception:
        pass

    # ── Todoist ───────────────────────────────────────────────────────────────
    tasks: list[TodoistTask] = []
    try:
        todoist = TodoistClient(todoist_token)
        tasks = todoist.get_tasks("!date | today | overdue")
    except Exception as exc:
        print(f"[plan-day] Todoist fetch failed: {exc}")

    # ── Filter into buckets ───────────────────────────────────────────────────
    _tz_obj = ZoneInfo(tz_str)
    already_scheduled: list[TodoistTask] = []
    schedulable: list[TodoistTask] = []
    skipped: list[TodoistTask] = []

    for t in tasks:
        if t.duration_minutes is None:
            skipped.append(t)
            continue
        if t.due_datetime is not None:
            dt = t.due_datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz_obj)
            else:
                dt = dt.astimezone(_tz_obj)
            if dt.date() == target_date:
                already_scheduled.append(t)
            continue
        schedulable.append(t)

    # ── Free windows ──────────────────────────────────────────────────────────
    windows = compute_free_windows(
        events,
        target_date,
        context,
        late_night_prior=late_night_prior,
        scheduled_tasks=already_scheduled,
    )

    # ── Mid-day context injection ──────────────────────────────────────────────
    schedule_context = context
    if target_date == date.today() and windows:
        now = datetime.now(tz=_tz_obj)
        ft = context.get("sleep", {}).get("first_task_not_before", "10:30")
        fth, ftm = map(int, ft.split(":"))
        morning_cutoff = datetime(target_date.year, target_date.month, target_date.day,
                                  fth, ftm, tzinfo=_tz_obj)
        if now > morning_cutoff:
            midday_rule = (
                f"NOTE: It is currently {now.strftime('%H:%M')}. The morning peak "
                f"window has passed. Schedule from the afternoon secondary peak onwards."
            )
            schedule_context = {
                **context,
                "rules": {
                    "hard": list(context.get("rules", {}).get("hard", [])) + [midday_rule],
                    "soft": list(context.get("rules", {}).get("soft", [])),
                },
            }

    if not schedulable and not already_scheduled:
        return PlanDayResponse(
            target_date=target_date.isoformat(),
            reasoning_summary="No schedulable tasks found.",
            scheduled=[],
            pushed=[],
            flagged=[],
            already_scheduled=[],
            skipped_count=len(skipped),
            free_windows_count=len(windows),
        )

    if not windows:
        return PlanDayResponse(
            target_date=target_date.isoformat(),
            reasoning_summary="No free windows available for this date.",
            scheduled=[],
            pushed=[],
            flagged=[],
            already_scheduled=[
                {"task_id": t.id, "content": t.content,
                 "due_datetime": t.due_datetime.isoformat() if t.due_datetime else None}
                for t in already_scheduled
            ],
            skipped_count=len(skipped),
            free_windows_count=0,
        )

    # ── LLM Step 1 — Enrich ───────────────────────────────────────────────────
    enrich_messages = build_enrich_prompt(schedulable, context, prod_science)
    try:
        enrich_raw = _anthropic_json_call(ant_client, enrich_messages, "enrich_tasks")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM enrich failed: {exc}") from exc

    # Normalize: LLM sometimes wraps the list in a dict
    if isinstance(enrich_raw, dict):
        for key in ("tasks", "enriched_tasks", "results", "data"):
            if key in enrich_raw and isinstance(enrich_raw[key], list):
                enrich_raw = enrich_raw[key]
                break

    enriched_list: list[dict] = enrich_raw if isinstance(enrich_raw, list) else []
    enriched_map: dict[str, dict] = {
        item.get("task_id", ""): item
        for item in enriched_list
        if isinstance(item, dict)
    }

    enriched_task_details = build_enriched_task_details(schedulable, enriched_map, _PRIORITY_LABEL)

    # ── LLM Step 2 — Schedule ─────────────────────────────────────────────────
    heuristics = prod_science.get("scheduling_heuristics_summary", prod_science)
    schedule_messages = build_schedule_prompt(
        enriched_task_details, windows, schedule_context, heuristics,
        target_date.isoformat(),
    )
    try:
        sched_raw = _anthropic_json_call(ant_client, schedule_messages, "generate_schedule")
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"LLM schedule failed: {exc}") from exc

    if not isinstance(sched_raw, dict):
        raise HTTPException(status_code=502, detail="LLM schedule returned unexpected format")

    for key in ("reasoning_summary", "ordered_tasks", "pushed", "flagged"):
        sched_raw.setdefault(key, [] if key != "reasoning_summary" else "")

    # ── pack_schedule ─────────────────────────────────────────────────────────
    blocks, overflow_pushed = pack_schedule(
        sched_raw.get("ordered_tasks", []),
        windows,
        context,
        target_date,
    )
    all_pushed = sched_raw.get("pushed", []) + overflow_pushed

    return PlanDayResponse(
        target_date=target_date.isoformat(),
        reasoning_summary=sched_raw.get("reasoning_summary", ""),
        scheduled=[
            ScheduledBlockOut(
                task_id=b.task_id,
                task_name=b.task_name,
                start_time=b.start_time.isoformat(),
                end_time=b.end_time.isoformat(),
                duration_minutes=b.duration_minutes,
                work_block=b.work_block,
                placement_reason=b.placement_reason,
                split_session=b.split_session,
                back_to_back=b.back_to_back,
            )
            for b in blocks
        ],
        pushed=all_pushed,
        flagged=sched_raw.get("flagged", []),
        already_scheduled=[
            {
                "task_id": t.id,
                "content": t.content,
                "due_datetime": (
                    t.due_datetime.astimezone(_tz_obj).isoformat()
                    if t.due_datetime else None
                ),
                "duration_minutes": t.duration_minutes,
            }
            for t in already_scheduled
        ],
        skipped_count=len(skipped),
        free_windows_count=len(windows),
    )
