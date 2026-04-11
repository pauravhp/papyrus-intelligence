"""
POST /api/onboard/stage1   — calendar scan + LLM draft (no auth state)
POST /api/onboard/stage2   — apply user answers to draft config
POST /api/onboard/stage3   — free-window audit against today's calendar
POST /api/onboard/promote  — write final config to Supabase users.config

All routes are authenticated. No file I/O — caller holds state between stages.

Auth: Bearer <supabase_jwt>  →  get_current_user dependency
"""

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from groq import Groq
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase
from src.calendar_client import get_events
from src.llm import _groq_json_call
from src.onboard_patterns import build_pattern_summary
from src.prompts.onboard import build_onboard_prompt
from src.scheduler import compute_free_windows

router = APIRouter(prefix="/api/onboard")

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "context.template.json"
ONBOARD_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DAYS_TO_SCAN = 14


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _set_nested(d: dict, field_path: str, value) -> None:
    """
    Apply value to d at the dot-notation field_path.
    Skips silently if an intermediate key is missing or if the leaf doesn't
    exist in the original structure (avoids injecting unknown keys).

    Copied from src/commands/onboard.py — lives here so the API has no
    dependency on CLI-only code paths.
    """
    keys = field_path.split(".")
    node = d
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            return
        node = node[key]
    leaf = keys[-1]
    if leaf in node:
        node[leaf] = value


# ── Stage 1 ───────────────────────────────────────────────────────────────────


class Stage1Request(BaseModel):
    timezone: str
    calendar_ids: list[str] = []
    groq_api_key: str
    todoist_api_key: str


class Stage1Response(BaseModel):
    proposed_config: dict
    questions_for_stage_2: list


@router.post("/stage1", response_model=Stage1Response)
def onboard_stage1(
    body: Stage1Request,
    user: dict = Depends(get_current_user),
) -> Stage1Response:
    """
    Stage 1: Scan 14 days of GCal, detect patterns, call LLM to propose
    a draft config (based on context.template.json). Returns the LLM output
    directly — no file I/O.
    """
    try:
        with open(TEMPLATE_PATH) as f:
            template: dict = json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="context.template.json not found on server",
        )

    context_for_prompt: dict = {
        "user": {"timezone": body.timezone},
        "calendar_ids": body.calendar_ids,
        **{k: v for k, v in template.items() if k not in ("user", "calendar_ids")},
    }

    today = date.today()
    start_date = today - timedelta(days=DAYS_TO_SCAN - 1)
    events_by_date: dict[date, list] = {}
    all_events: list = []

    for i in range(DAYS_TO_SCAN):
        target = start_date + timedelta(days=i)
        try:
            day_events = get_events(
                target_date=target,
                timezone_str=body.timezone,
                extra_calendar_ids=body.calendar_ids,
            )
            events_by_date[target] = day_events
            all_events.extend(day_events)
        except Exception as exc:
            print(f"[onboard/stage1] Warning: could not fetch {target}: {exc}")
            events_by_date[target] = []

    patterns = build_pattern_summary(events_by_date, all_events)
    groq_client = Groq(api_key=body.groq_api_key)
    messages = build_onboard_prompt(patterns, context_for_prompt)

    try:
        raw = _groq_json_call(groq_client, ONBOARD_MODEL, messages, "onboard_stage1")
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"LLM call failed: {exc}") from exc

    if not isinstance(raw, dict):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Unexpected LLM response type: {type(raw).__name__}")

    return Stage1Response(
        proposed_config=raw.get("proposed_config") or {},
        questions_for_stage_2=raw.get("questions_for_stage_2") or [],
    )


# ── Stage 2 ───────────────────────────────────────────────────────────────────


class AnswerItem(BaseModel):
    field: str   # dot-notation path into draft_config, e.g. "sleep.default_wake_time"
    value: str   # raw string; _minutes/_min fields are coerced to int


class Stage2Request(BaseModel):
    draft_config: dict
    answers: list[AnswerItem]


class Stage2Response(BaseModel):
    updated_config: dict
    answers_applied: int


@router.post("/stage2", response_model=Stage2Response)
def onboard_stage2(
    body: Stage2Request,
    user: dict = Depends(get_current_user),
) -> Stage2Response:
    """
    Stage 2: Apply user answers to the draft config from Stage 1.

    For each { field, value } pair:
    - Coerce to int if field ends with _minutes or _min and value parses as int.
    - Apply to draft_config via dot-notation path (_set_nested).
    - Silently skip unknown paths — never injects new keys into the draft.

    Returns the updated draft_config. No file I/O, no DB writes.
    """
    draft = copy.deepcopy(body.draft_config)
    applied = 0

    for answer in body.answers:
        raw_value: str | int = answer.value

        if raw_value not in (None, "", "null"):
            if answer.field.endswith("_minutes") or answer.field.endswith("_min"):
                try:
                    raw_value = int(raw_value)
                except ValueError:
                    pass

        _set_nested(draft, answer.field, raw_value)
        applied += 1

    return Stage2Response(updated_config=draft, answers_applied=applied)


# ── Stage 3 ───────────────────────────────────────────────────────────────────


class Stage3Request(BaseModel):
    draft_config: dict
    timezone: str
    calendar_ids: list[str] = []


class FreeWindowOut(BaseModel):
    start: str          # ISO 8601
    end: str            # ISO 8601
    duration_minutes: int
    block_type: str


class EventOut(BaseModel):
    summary: str
    start: str
    end: str
    color_id: str | None
    is_all_day: bool


class Stage3Response(BaseModel):
    free_windows: list[FreeWindowOut]
    events_consuming_time: list[EventOut]
    effective_wake: str | None       # HH:MM from draft config
    first_task_not_before: str | None


@router.post("/stage3", response_model=Stage3Response)
def onboard_stage3(
    body: Stage3Request,
    user: dict = Depends(get_current_user),
) -> Stage3Response:
    """
    Stage 3: Free-window audit.

    Strips _onboard_draft from draft_config, fetches today's GCal events,
    runs compute_free_windows() with the draft config, and returns the windows
    + consuming events for the frontend to display as a visual confirmation.

    No Todoist calls. No LLM calls. GCal read-only.
    """
    working = copy.deepcopy(body.draft_config)
    working.pop("_onboard_draft", None)

    # Inject timezone if draft has null (compute_free_windows needs it)
    if working.get("user", {}).get("timezone") is None:
        working.setdefault("user", {})["timezone"] = body.timezone
    if not working.get("calendar_ids"):
        working["calendar_ids"] = body.calendar_ids

    today = date.today()
    events = []
    try:
        events = get_events(
            target_date=today,
            timezone_str=body.timezone,
            extra_calendar_ids=body.calendar_ids,
        )
    except Exception as exc:
        print(f"[onboard/stage3] Warning: GCal fetch failed: {exc}")

    windows = compute_free_windows(events, today, working)

    tz_str = body.timezone
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("UTC")

    free_windows_out = [
        FreeWindowOut(
            start=w.start.isoformat(),
            end=w.end.isoformat(),
            duration_minutes=w.duration_minutes,
            block_type=w.block_type,
        )
        for w in windows
    ]

    # Events that actually consume time (non-all-day)
    events_out = [
        EventOut(
            summary=ev.summary,
            start=ev.start.isoformat(),
            end=ev.end.isoformat(),
            color_id=ev.color_id,
            is_all_day=ev.is_all_day,
        )
        for ev in events
        if not ev.is_all_day
    ]

    sleep = working.get("sleep", {})
    return Stage3Response(
        free_windows=free_windows_out,
        events_consuming_time=events_out,
        effective_wake=sleep.get("default_wake_time"),
        first_task_not_before=sleep.get("first_task_not_before"),
    )


# ── Promote ───────────────────────────────────────────────────────────────────


class PromoteRequest(BaseModel):
    draft_config: dict


class PromoteResponse(BaseModel):
    success: bool


@router.post("/promote", response_model=PromoteResponse)
def onboard_promote(
    body: PromoteRequest,
    user: dict = Depends(get_current_user),
) -> PromoteResponse:
    """
    Promote: strip _onboard_draft from draft_config and write it to
    users.config in Supabase for the authenticated user.

    user_id comes from the verified JWT — never trusted from the request body.

    Note: users.config is plain jsonb (not encrypted). Encrypted credential
    columns (todoist_api_key, groq_api_key, google_credentials) are written
    by a separate credential-save step (not yet implemented) and require a
    SQL wrapper function to set the encryption key within the same transaction.
    """
    user_id: str = user["sub"]

    clean_config = copy.deepcopy(body.draft_config)
    clean_config.pop("_onboard_draft", None)

    # users.config is plain jsonb — no encryption needed for this column.
    # set_encryption_key() will be required once todoist_api_key / groq_api_key
    # are written (separate credential-save step, not yet implemented).
    result = (
        supabase.from_("users")
        .update({"config": clean_config})
        .eq("id", user_id)
        .execute()
    )

    if hasattr(result, "error") and result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Supabase write failed: {result.error}",
        )

    return PromoteResponse(success=True)
