# api/routes/onboard.py
"""
POST /api/onboard/scan     — 14-day GCal scan → proposed config
POST /api/onboard/promote  — save final config to users.config
"""

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from google.oauth2.credentials import Credentials
from pydantic import BaseModel

from api.auth import get_current_user, require_beta_access
from api.services.analytics import capture
from api.services.sync_detector import detect_todoist_gcal_sync
from api.config import settings
from api.db import supabase
from src.calendar_client import GcalReconnectRequired, WRITE_SCOPES, build_gcal_service_from_credentials, get_events
from src.gcal_colors import GCAL_COLOR_IDS, GCAL_COLOR_NAMES
from src.llm import _anthropic_json_call, _extract_json
from src.onboard_patterns import build_pattern_summary
from src.prompts.onboard import build_onboard_prompt

router = APIRouter(prefix="/api/onboard")

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "context.template.json"
DAYS_TO_SCAN = 14


# ── scan ──────────────────────────────────────────────────────────────────────


class ScanRequest(BaseModel):
    timezone: str
    calendar_ids: list[str] = []


class DetectedCategory(BaseModel):
    name: str
    color_name: str
    color_id: str | None
    event_samples: list[str]
    buffer_before_minutes: int
    buffer_after_minutes: int


class ScanResponse(BaseModel):
    proposed_config: dict
    questions: list
    detected_categories: list[DetectedCategory]


def _translate_color_semantics(semantics: dict) -> dict:
    """Replace raw color_id keys with human color names; drop entries with count < 2."""
    return {
        GCAL_COLOR_NAMES.get(cid, cid): data
        for cid, data in semantics.items()
        if data.get("count", 0) >= 2
    }


def _build_detected_categories(raw: list[dict]) -> list[DetectedCategory]:
    result = []
    for item in raw:
        color_name = item.get("color_name", "")
        color_id = GCAL_COLOR_IDS.get(color_name)  # None if unrecognised
        buf_before = item.get("buffer_before_minutes", 15)
        buf_after = item.get("buffer_after_minutes", 15)
        valid = {0, 5, 15, 30}
        result.append(DetectedCategory(
            name=item.get("name", "Untitled"),
            color_name=color_name,
            color_id=color_id,
            event_samples=item.get("event_samples", [])[:3],
            buffer_before_minutes=buf_before if buf_before in valid else 15,
            buffer_after_minutes=buf_after if buf_after in valid else 15,
        ))
    return result


def _categories_to_calendar_rules(categories: list[DetectedCategory]) -> dict:
    return {
        cat.name: {
            "color_id": cat.color_id,
            "buffer_before_minutes": cat.buffer_before_minutes,
            "buffer_after_minutes": cat.buffer_after_minutes,
            "movable": False,
        }
        for cat in categories
    }


def _default_calendar_rules() -> dict:
    return {
        "Meetings & calls": {
            "color_id": None,
            "buffer_before_minutes": 15,
            "buffer_after_minutes": 15,
            "movable": False,
        },
        "Personal commitments": {
            "color_id": None,
            "buffer_before_minutes": 30,
            "buffer_after_minutes": 30,
            "movable": False,
        },
    }


@router.post("/scan", response_model=ScanResponse)
def onboard_scan(
    body: ScanRequest,
    user: dict = Depends(require_beta_access),
) -> ScanResponse:
    """
    Scan the last 14 days of Google Calendar to propose a schedule config.
    Uses server-side ANTHROPIC_API_KEY — no LLM key needed from user.
    """
    user_id: str = user["sub"]

    row_result = (
        supabase.from_("users")
        .select("google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=400, detail="User not found.")

    creds_data: dict | None = row_result.data.get("google_credentials")
    if not creds_data:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected. Complete OAuth at /auth/google first.",
        )

    ant_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build GCal service
    try:
        gcal_service, refreshed = build_gcal_service_from_credentials(
            creds_data, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        )
        if refreshed:
            supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
    except GcalReconnectRequired as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "gcal_reconnect_required", "message": str(exc)},
        )

    # Load template
    try:
        with open(TEMPLATE_PATH) as f:
            template: dict = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="context.template.json not found on server.")

    context_for_prompt: dict = {
        "user": {"timezone": body.timezone},
        "calendar_ids": body.calendar_ids,
        **{k: v for k, v in template.items() if k not in ("user", "calendar_ids")},
    }

    # Scan 14 days
    today = date.today()
    start_date = today - timedelta(days=DAYS_TO_SCAN - 1)
    events_by_date: dict = {}
    all_events: list = []

    for i in range(DAYS_TO_SCAN):
        target = start_date + timedelta(days=i)
        try:
            day_events = get_events(
                target_date=target,
                timezone_str=body.timezone,
                calendar_ids=body.calendar_ids,
                service=gcal_service,
            )
            events_by_date[target] = day_events
            all_events.extend(day_events)
        except Exception as exc:
            print(f"[onboard/scan] Warning: could not fetch {target}: {exc}")
            events_by_date[target] = []

    patterns = build_pattern_summary(events_by_date, all_events)
    patterns["color_semantics"] = _translate_color_semantics(
        patterns.get("color_semantics", {})
    )
    messages = build_onboard_prompt(patterns, context_for_prompt)

    try:
        raw = _anthropic_json_call(ant_client, messages, "onboard_scan")
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="Unexpected LLM response shape.")

    detected = _build_detected_categories(raw.get("detected_categories") or [])
    calendar_rules = _categories_to_calendar_rules(detected) if detected else _default_calendar_rules()

    proposed = raw.get("proposed_config") or {}
    proposed["calendar_rules"] = calendar_rules

    # Browser-detected timezone (body.timezone) is authoritative — the LLM is
    # not asked for it and must not be trusted with it. Without this overwrite
    # the saved config has user.timezone=None and the planner silently falls
    # back to America/Vancouver for everyone.
    user_block = proposed.get("user") or {}
    user_block["timezone"] = body.timezone
    proposed["user"] = user_block

    return ScanResponse(
        proposed_config=proposed,
        questions=raw.get("questions_for_stage_2") or [],
        detected_categories=detected,
    )


# ── detect-todoist-sync ───────────────────────────────────────────────────────


class DetectTodoistSyncResponse(BaseModel):
    detected: bool
    calendar_id: str | None


@router.get("/detect-todoist-sync", response_model=DetectTodoistSyncResponse)
def detect_todoist_sync(user: dict = Depends(get_current_user)) -> DetectTodoistSyncResponse:
    """Check whether Todoist's GCal integration is enabled. See PRE-RELEASE.md #9.

    Called by SetupStage after Todoist connects, and by Settings on page load.
    The user has to flip the toggle in Todoist's web UI themselves —
    Todoist doesn't expose an API to do it.
    """
    user_id: str = user["sub"]

    row_result = (
        supabase.from_("users")
        .select("google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=400, detail="User not found.")

    creds_data = row_result.data.get("google_credentials")
    if not creds_data:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected.",
        )

    try:
        gcal_service, refreshed = build_gcal_service_from_credentials(
            creds_data, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        )
        if refreshed:
            supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
    except GcalReconnectRequired as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "gcal_reconnect_required", "message": str(exc)},
        )

    result = detect_todoist_gcal_sync(gcal_service)
    return DetectTodoistSyncResponse(**result)


# ── promote ───────────────────────────────────────────────────────────────────


class PromoteRequest(BaseModel):
    config: dict


class PromoteResponse(BaseModel):
    success: bool


@router.post("/promote", response_model=PromoteResponse)
def onboard_promote(
    body: PromoteRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_beta_access),
) -> PromoteResponse:
    """
    Save the confirmed config to users.config.
    """
    user_id: str = user["sub"]

    clean = copy.deepcopy(body.config)
    clean.pop("_onboard_draft", None)

    try:
        supabase.from_("users").update({"config": clean}).eq("id", user_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Supabase write failed: {exc}")

    background_tasks.add_task(
        capture,
        user_id,
        "onboarding_completed",
        {
            "timezone": (clean.get("user") or {}).get("timezone", ""),
            "has_google_calendar": bool(clean.get("source_calendar_ids") or clean.get("calendar_ids")),
        },
    )

    return PromoteResponse(success=True)
