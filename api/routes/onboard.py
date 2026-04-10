"""
POST /api/onboard/stage1

Authenticated. Mirrors the CLI --onboard Stage 1 logic but:
- Takes credentials from the request body (not .env / context.json)
- Returns the raw LLM output to the caller instead of writing to disk
- No file I/O; caller holds state between stages

Auth: Bearer <supabase_jwt>  →  get_current_user dependency
"""

import json
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from groq import Groq
from pydantic import BaseModel

from api.auth import get_current_user
from src.calendar_client import get_events
from src.llm import _groq_json_call
from src.onboard_patterns import build_pattern_summary
from src.prompts.onboard import build_onboard_prompt

router = APIRouter(prefix="/api/onboard")

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "context.template.json"
ONBOARD_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DAYS_TO_SCAN = 14


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
    Stage 1 of multi-user onboarding:

    1. Load context.template.json as the draft base.
    2. Fetch 14 days of GCal events using the caller-supplied timezone +
       calendar_ids (uses local OAuth token.json for GCal auth).
    3. Detect calendar patterns (wake times, color semantics, recurring blocks).
    4. Call the LLM to propose a draft config and questions for Stage 2.
    5. Return { proposed_config, questions_for_stage_2 } — no file I/O.
    """
    # ── Load template ──────────────────────────────────────────────────────────
    try:
        with open(TEMPLATE_PATH) as f:
            template: dict = json.load(f)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="context.template.json not found on server",
        )

    # Build a minimal context dict so build_onboard_prompt can reference it.
    # Matches what the CLI passes: timezone + calendar_ids from the request.
    context_for_prompt: dict = {
        "user": {"timezone": body.timezone},
        "calendar_ids": body.calendar_ids,
        **{k: v for k, v in template.items() if k not in ("user", "calendar_ids")},
    }

    # ── Fetch 14 days of GCal events ──────────────────────────────────────────
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
            # Non-fatal: log and continue with an empty day
            print(f"[onboard/stage1] Warning: could not fetch {target}: {exc}")
            events_by_date[target] = []

    # ── Pattern detection ──────────────────────────────────────────────────────
    patterns = build_pattern_summary(events_by_date, all_events)

    # ── LLM call ──────────────────────────────────────────────────────────────
    groq_client = Groq(api_key=body.groq_api_key)
    messages = build_onboard_prompt(patterns, context_for_prompt)

    try:
        raw = _groq_json_call(groq_client, ONBOARD_MODEL, messages, "onboard_stage1")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM call failed: {exc}",
        ) from exc

    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unexpected LLM response type: {type(raw).__name__}",
        )

    return Stage1Response(
        proposed_config=raw.get("proposed_config") or {},
        questions_for_stage_2=raw.get("questions_for_stage_2") or [],
    )
