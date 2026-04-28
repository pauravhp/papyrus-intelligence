"""
/api/import/convert and /api/import/commit — the two routes for the
task migration assistant.

`/convert` parses a raw text dump into structured tasks + rhythms.
No external writes.

`/commit` takes the (user-edited) proposal and writes:
- tasks → Todoist via TodoistClient.create_task
- rhythms → Supabase via rhythm_service.create_rhythm
- finds-or-creates the user's "Papyrus" GCal calendar via
  api.services.import_calendar.ensure_papyrus_calendar; surfaces
  calendar_scope_upgrade_required when re-OAuth is needed.

CLAUDE.md Rule 2: writes are human-gated. /convert never writes.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from google.oauth2.credentials import Credentials

from api.auth import require_beta_access
from api.config import settings
from api.db import supabase
from api.services.import_calendar import (
    PapyrusCalendarScopeError,
    ensure_papyrus_calendar,
)
from api.services.migration_parser import (
    MAX_INPUT_CHARS,
    MigrationParseError,
    parse_migration_dump,
)
from api.services.rhythm_service import create_rhythm
from api.services.todoist_token import (
    TodoistTokenError,
    get_valid_todoist_token,
    surface_todoist_auth_failure,
)
from src.todoist_client import TodoistClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["import"])

# UX-level minimum input length enforced at the route layer.
# The service's MIN_INPUT_CHARS is 1 (structural non-empty guard only);
# we enforce the user-facing 20-char floor here so the parser unit tests
# can still use short stub strings.
_ROUTE_MIN_INPUT_CHARS = 20


# ── Request / Response models ─────────────────────────────────────────────────


class ConvertRequest(BaseModel):
    raw_text: str
    target_date: str | None = None


class TaskProposal(BaseModel):
    content: str
    priority: int = Field(ge=1, le=4)
    duration_minutes: int = Field(ge=10, le=240)
    category_label: str | None = None
    deadline: str | None = None
    reasoning: str = ""


class RhythmProposal(BaseModel):
    name: str
    scheduling_hint: str = ""
    sessions_per_week: int = Field(ge=1, le=21)
    session_min_minutes: int
    session_max_minutes: int
    days_of_week: list[str]
    reasoning: str = ""


class ConvertResponse(BaseModel):
    tasks: list[TaskProposal]
    rhythms: list[RhythmProposal]
    unmatched: list[str]


class CommitRequest(BaseModel):
    tasks: list[TaskProposal]
    rhythms: list[RhythmProposal]


class CommitError(BaseModel):
    kind: str
    name: str
    reason: str


class CommitResponse(BaseModel):
    tasks_created: int
    rhythms_created: int
    errors: list[CommitError]
    todoist_reconnect_required: bool = False
    papyrus_calendar_id: str | None = None
    calendar_scope_upgrade_required: bool = False


# ── Helpers (module-scope so tests can patch them) ────────────────────────────


def _build_todoist_client(user_id: str) -> TodoistClient:
    token = get_valid_todoist_token(supabase, user_id)
    return TodoistClient(api_token=token)


def _build_task_labels(t: TaskProposal) -> list[str]:
    """Build the Todoist label list: duration tag + optional category tag."""
    labels: list[str] = [f"{t.duration_minutes}min"]
    if t.category_label:
        # Strip leading "@" — Todoist stores labels without it.
        labels.append(t.category_label.lstrip("@"))
    return labels


def _load_user_credentials(user_id: str):
    """Load the user's stored Google credentials.
    Returns (Credentials, timezone_str) or (None, None) if not connected."""
    row = (
        supabase.from_("users")
        .select("google_credentials, config")
        .eq("id", user_id)
        .single()
        .execute()
    )
    creds_data = (row.data or {}).get("google_credentials")
    if not creds_data:
        return None, None
    config = (row.data or {}).get("config") or {}
    timezone_str = (config.get("user") or {}).get("timezone", "UTC")
    creds = Credentials.from_authorized_user_info(creds_data)
    return creds, timezone_str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/convert", response_model=ConvertResponse)
def convert(
    body: ConvertRequest,
    user: dict = Depends(require_beta_access),
) -> ConvertResponse:
    """Parse a raw task dump into structured tasks + rhythms. No external writes."""
    text = (body.raw_text or "").strip()

    # Route-level UX floor (service MIN is 1; we enforce the 20-char minimum here).
    if len(text) < _ROUTE_MIN_INPUT_CHARS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "input_too_short",
                "message": f"Paste at least {_ROUTE_MIN_INPUT_CHARS} characters.",
            },
        )
    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "input_too_long",
                "message": f"Paste no more than {MAX_INPUT_CHARS} characters.",
            },
        )

    today = date.fromisoformat(body.target_date) if body.target_date else date.today()
    try:
        result = parse_migration_dump(
            raw_text=text,
            today=today,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": str(exc), "message": str(exc)},
        )
    except MigrationParseError as exc:
        logger.error("[import] parse failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "parse_failed",
                "message": "We couldn't read the response from the model. Try again.",
            },
        )

    return ConvertResponse(**result)


@router.post("/commit", response_model=CommitResponse)
def commit(
    body: CommitRequest,
    user: dict = Depends(require_beta_access),
) -> CommitResponse:
    """Write approved tasks to Todoist, rhythms to Supabase, and ensure the
    Papyrus GCal calendar exists."""
    user_id = user["sub"]

    # Fail fast on Todoist auth issues before attempting any writes.
    try:
        client = _build_todoist_client(user_id)
    except TodoistTokenError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "todoist_reconnect_required", "message": str(exc)},
        )
    except RuntimeError as exc:
        surface_todoist_auth_failure(exc)

    errors: list[CommitError] = []
    tasks_created = 0
    rhythms_created = 0

    for t in body.tasks:
        try:
            client.create_task(
                content=t.content,
                priority=t.priority,
                deadline=t.deadline,
                labels=_build_task_labels(t),
            )
            tasks_created += 1
        except RuntimeError as exc:
            if "Todoist API auth failed" in str(exc):
                surface_todoist_auth_failure(exc)
            errors.append(CommitError(kind="task", name=t.content, reason=str(exc)[:200]))
        except Exception as exc:
            errors.append(CommitError(kind="task", name=t.content, reason=str(exc)[:200]))

    for r in body.rhythms:
        try:
            create_rhythm(
                user_id,
                supabase,
                name=r.name,
                sessions_per_week=r.sessions_per_week,
                session_min=r.session_min_minutes,
                session_max=r.session_max_minutes,
                description=r.scheduling_hint or None,
                days_of_week=r.days_of_week,
                sort_order=0,
            )
            rhythms_created += 1
        except Exception as exc:
            logger.exception("[import] rhythm create failed for %s", r.name)
            errors.append(CommitError(kind="rhythm", name=r.name, reason=str(exc)[:200]))

    papyrus_calendar_id: str | None = None
    calendar_scope_upgrade_required = False

    creds, timezone_str = _load_user_credentials(user_id)
    if creds is not None:
        try:
            papyrus_calendar_id = ensure_papyrus_calendar(
                user_id=user_id,
                supabase=supabase,
                credentials=creds,
                timezone_str=timezone_str or "UTC",
            )
        except PapyrusCalendarScopeError:
            calendar_scope_upgrade_required = True
        except Exception as exc:
            logger.exception("[import] papyrus calendar ensure failed")
            errors.append(
                CommitError(kind="calendar", name="<papyrus>", reason=str(exc)[:200])
            )

    return CommitResponse(
        tasks_created=tasks_created,
        rhythms_created=rhythms_created,
        errors=errors,
        todoist_reconnect_required=False,
        papyrus_calendar_id=papyrus_calendar_id,
        calendar_scope_upgrade_required=calendar_scope_upgrade_required,
    )
