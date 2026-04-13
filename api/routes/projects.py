"""
/api/projects — Project budget CRUD.

All routes require Bearer JWT. user_id comes from the verified token.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase
from api.services.project_service import (
    create_project,
    delete_project,
    get_active_projects,
    log_session,
    reset_project,
    update_project,
)

router = APIRouter(prefix="/api/projects")


class CreateProjectRequest(BaseModel):
    name: str
    total_hours: float
    session_min: int = 60
    session_max: int = 180
    deadline: str | None = None
    priority: int = 3  # 4=P1, 3=P2, 2=P3, 1=P4


class UpdateProjectRequest(BaseModel):
    session_min: int | None = None
    session_max: int | None = None
    deadline: str | None = None
    priority: int | None = None
    add_hours: float | None = None


class LogSessionRequest(BaseModel):
    hours_worked: float


@router.get("")
def list_projects(user: dict = Depends(get_current_user)):
    return get_active_projects(user["sub"], supabase)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project_route(
    body: CreateProjectRequest,
    user: dict = Depends(get_current_user),
):
    return create_project(
        user["sub"], supabase,
        name=body.name,
        total_hours=body.total_hours,
        session_min=body.session_min,
        session_max=body.session_max,
        deadline=body.deadline,
        priority=body.priority,
    )


@router.patch("/{project_id}")
def update_project_route(
    project_id: int,
    body: UpdateProjectRequest,
    user: dict = Depends(get_current_user),
):
    return update_project(
        user["sub"], supabase, project_id=project_id,
        session_min=body.session_min,
        session_max=body.session_max,
        deadline=body.deadline,
        priority=body.priority,
        add_hours=body.add_hours,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_route(project_id: int, user: dict = Depends(get_current_user)):
    delete_project(user["sub"], supabase, project_id)


@router.post("/{project_id}/reset")
def reset_project_route(project_id: int, user: dict = Depends(get_current_user)):
    return reset_project(user["sub"], supabase, project_id)


@router.post("/{project_id}/log")
def log_session_route(
    project_id: int,
    body: LogSessionRequest,
    user: dict = Depends(get_current_user),
):
    if body.hours_worked <= 0:
        raise HTTPException(status_code=400, detail="hours_worked must be > 0")
    return log_session(user["sub"], supabase, project_id, body.hours_worked)
