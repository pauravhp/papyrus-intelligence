"""
/api/rhythms — Rhythm CRUD.

All routes require Bearer JWT. user_id comes from the verified token.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel

from api.auth import get_current_user, require_beta_access
from api.db import supabase
from api.services.analytics import capture
from api.services.rhythm_service import (
    _DESCRIPTION_UNSET,
    create_rhythm,
    delete_rhythm,
    get_active_rhythms,
    update_rhythm,
)

router = APIRouter(prefix="/api/rhythms")


class CreateRhythmRequest(BaseModel):
    name: str
    sessions_per_week: int
    session_min: int = 60
    session_max: int = 120
    end_date: str | None = None
    sort_order: int = 0
    description: str | None = None


class UpdateRhythmRequest(BaseModel):
    sessions_per_week: int | None = None
    session_min: int | None = None
    session_max: int | None = None
    end_date: str | None = None
    sort_order: int | None = None
    description: str | None = None


@router.get("")
def list_rhythms(user: dict = Depends(require_beta_access)):
    return get_active_rhythms(user["sub"], supabase)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_rhythm_route(
    body: CreateRhythmRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_beta_access),
):
    desc = body.description.strip() if body.description else None
    result = create_rhythm(
        user["sub"], supabase,
        name=body.name,
        sessions_per_week=body.sessions_per_week,
        session_min=body.session_min,
        session_max=body.session_max,
        end_date=body.end_date,
        sort_order=body.sort_order,
        description=desc,
    )
    background_tasks.add_task(
        capture,
        user["sub"],
        "rhythm_created",
        {
            "sessions_per_week": body.sessions_per_week,
            "has_end_date": body.end_date is not None,
        },
    )
    return result


@router.patch("/{rhythm_id}")
def update_rhythm_route(
    rhythm_id: int,
    body: UpdateRhythmRequest,
    user: dict = Depends(require_beta_access),
):
    # Use model_fields_set to detect whether description was present in the request
    # body at all. If absent, pass the sentinel so the service leaves it unchanged.
    if "description" in body.model_fields_set:
        desc = body.description.strip() if body.description else None
    else:
        desc = _DESCRIPTION_UNSET

    return update_rhythm(
        user["sub"], supabase, rhythm_id=rhythm_id,
        sessions_per_week=body.sessions_per_week,
        session_min=body.session_min,
        session_max=body.session_max,
        end_date=body.end_date,
        sort_order=body.sort_order,
        description=desc,
    )


@router.delete("/{rhythm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rhythm_route(rhythm_id: int, user: dict = Depends(require_beta_access)):
    delete_rhythm(user["sub"], supabase, rhythm_id)
