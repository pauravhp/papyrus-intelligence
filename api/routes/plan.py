"""
Direct planning endpoints for the Today panel.

Three routes, no agent loop:
  POST /api/plan         — initial plan for today or tomorrow
  POST /api/refine       — refine an existing proposal
  POST /api/plan/confirm — write the proposed schedule to GCal + Todoist

Each route is one LLM call (or zero, for confirm).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user, require_beta_access
from api.config import settings
from api.db import supabase
from api.services import planner
from api.services.todoist_token import TodoistTokenError, get_valid_todoist_token
from src.calendar_client import build_gcal_service_from_credentials

router = APIRouter(prefix="/api")


# ── Request/Response models ───────────────────────────────────────────────────


class PlanRequest(BaseModel):
    target_date: Literal["today", "tomorrow"] = "today"
    context_note: str | None = None


class RefineRequest(BaseModel):
    target_date: Literal["today", "tomorrow"] = "today"
    previous_proposal: dict
    refinement_message: str
    original_context_note: str | None = None


class ConfirmRequest(BaseModel):
    target_date: Literal["today", "tomorrow"] = "today"
    schedule: dict


class PlanResponse(BaseModel):
    scheduled: list[dict]
    pushed: list[dict]
    reasoning_summary: str
    free_windows_used: list[dict]
    blocks: list[dict] = []  # carry-forward time-block constraints
    cutoff_override: str | None = None  # carry-forward end-of-day cutoff (ISO datetime)
    # True when "Plan today" was invoked past the user's effective cutoff and
    # the planner short-circuited with an empty schedule. Frontend pivots on
    # this to render a "Plan tomorrow" CTA instead of an empty grid.
    auto_shift_to_tomorrow_suggested: bool = False


class ConfirmResponse(BaseModel):
    confirmed: bool
    gcal_events_created: int
    todoist_updated: int
    schedule_log_id: int | None = None


# ── Shared user-context loader ────────────────────────────────────────────────


def _load_user_ctx(user_id: str) -> dict:
    """
    Load config + Todoist token + GCal service for a user. Mirrors the loader
    in replan.py — kept local here so the planning surface owns its own
    construction without coupling to the legacy chat path.
    """
    row_result = (
        supabase.from_("users")
        .select("config, todoist_oauth_token, google_credentials")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=400, detail="User not found or not onboarded.")

    row = row_result.data
    config = row.get("config") or {}
    if not config:
        raise HTTPException(status_code=400, detail="User config is empty. Complete onboarding first.")

    if not (row.get("todoist_oauth_token") or {}).get("access_token"):
        raise HTTPException(status_code=400, detail="Todoist not connected.")

    try:
        todoist_token = get_valid_todoist_token(supabase, user_id)
    except TodoistTokenError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "todoist_reconnect_required", "message": str(exc)},
        )

    gcal_creds = row.get("google_credentials")
    gcal_service = None
    if gcal_creds:
        try:
            svc, refreshed = build_gcal_service_from_credentials(
                gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET,
            )
            gcal_service = svc
            if refreshed:
                supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
        except Exception as exc:
            print(f"[plan] GCal service init failed: {exc}")

    return {
        "user_id": user_id,
        "config": config,
        "todoist_api_key": todoist_token,
        "gcal_service": gcal_service,
        "supabase": supabase,
        "anthropic_api_key": settings.ANTHROPIC_API_KEY,
    }


def _resolve_date(label: str) -> date:
    if label == "tomorrow":
        from datetime import timedelta
        return date.today() + timedelta(days=1)
    return date.today()


# ── Routes ────────────────────────────────────────────────────────────────────


def _surface_todoist_auth_failure(exc: RuntimeError) -> None:
    """If a downstream Todoist call hit a 401 (token revoked between our
    refresh-check and the actual API call — a race we can't prevent), raise
    a structured 400 so the frontend renders the reconnect surface."""
    if "Todoist API auth failed" in str(exc):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "todoist_reconnect_required",
                "message": "Todoist connection lost — please reconnect",
            },
        )
    raise exc


@router.post("/plan", response_model=PlanResponse)
def plan(body: PlanRequest, user: dict = Depends(require_beta_access)) -> PlanResponse:
    """Propose a schedule for target_date. One LLM call. No external writes."""
    user_ctx = _load_user_ctx(user["sub"])
    target_date = _resolve_date(body.target_date)
    try:
        result = planner.plan(user_ctx, target_date, body.context_note or "")
    except RuntimeError as exc:
        _surface_todoist_auth_failure(exc)
    return PlanResponse(
        scheduled=result.get("scheduled", []),
        pushed=result.get("pushed", []),
        reasoning_summary=result.get("reasoning_summary", ""),
        free_windows_used=result.get("free_windows_used", []),
        blocks=result.get("blocks", []),
        cutoff_override=result.get("cutoff_override"),
        auto_shift_to_tomorrow_suggested=result.get("auto_shift_to_tomorrow_suggested", False),
    )


@router.post("/refine", response_model=PlanResponse)
def refine(body: RefineRequest, user: dict = Depends(require_beta_access)) -> PlanResponse:
    """Refine an existing proposal with a new instruction. One LLM call."""
    user_ctx = _load_user_ctx(user["sub"])
    target_date = _resolve_date(body.target_date)
    try:
        result = planner.refine(
            user_ctx,
            target_date,
            previous_proposal=body.previous_proposal,
            refinement_message=body.refinement_message,
            original_context_note=body.original_context_note or "",
        )
    except RuntimeError as exc:
        _surface_todoist_auth_failure(exc)
    return PlanResponse(
        scheduled=result.get("scheduled", []),
        pushed=result.get("pushed", []),
        reasoning_summary=result.get("reasoning_summary", ""),
        free_windows_used=result.get("free_windows_used", []),
        blocks=result.get("blocks", []),
        cutoff_override=result.get("cutoff_override"),
        auto_shift_to_tomorrow_suggested=result.get("auto_shift_to_tomorrow_suggested", False),
    )


@router.post("/plan/confirm", response_model=ConfirmResponse)
def confirm(body: ConfirmRequest, user: dict = Depends(require_beta_access)) -> ConfirmResponse:
    """Write the proposed schedule to GCal + Todoist + schedule_log."""
    user_ctx = _load_user_ctx(user["sub"])
    target_date = _resolve_date(body.target_date)
    try:
        result = planner.confirm(user_ctx, body.schedule, target_date)
    except planner.AlreadyConfirmedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        _surface_todoist_auth_failure(exc)
    return ConfirmResponse(**result)
