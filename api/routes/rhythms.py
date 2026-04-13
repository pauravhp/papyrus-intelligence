"""
/api/rhythms — Rhythm CRUD.

All routes require Bearer JWT. user_id comes from the verified token.
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase
from api.services.rhythm_service import (
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


class UpdateRhythmRequest(BaseModel):
    sessions_per_week: int | None = None
    session_min: int | None = None
    session_max: int | None = None
    end_date: str | None = None
    sort_order: int | None = None


@router.get("")
def list_rhythms(user: dict = Depends(get_current_user)):
    return get_active_rhythms(user["sub"], supabase)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_rhythm_route(body: CreateRhythmRequest, user: dict = Depends(get_current_user)):
    return create_rhythm(
        user["sub"], supabase,
        name=body.name,
        sessions_per_week=body.sessions_per_week,
        session_min=body.session_min,
        session_max=body.session_max,
        end_date=body.end_date,
        sort_order=body.sort_order,
    )


@router.patch("/{rhythm_id}")
def update_rhythm_route(
    rhythm_id: int,
    body: UpdateRhythmRequest,
    user: dict = Depends(get_current_user),
):
    return update_rhythm(
        user["sub"], supabase, rhythm_id=rhythm_id,
        sessions_per_week=body.sessions_per_week,
        session_min=body.session_min,
        session_max=body.session_max,
        end_date=body.end_date,
        sort_order=body.sort_order,
    )


@router.delete("/{rhythm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rhythm_route(rhythm_id: int, user: dict = Depends(get_current_user)):
    delete_rhythm(user["sub"], supabase, rhythm_id)
