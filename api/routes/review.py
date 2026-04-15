# api/routes/review.py

import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase

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
    tasks: list[ReviewSubmitTask]
    rhythms: list[ReviewSubmitRhythm]


@router.get("/review/preflight")
def review_preflight(user: dict = Depends(get_current_user)) -> dict:
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/review/submit")
def review_submit(body: ReviewSubmitRequest, user: dict = Depends(get_current_user)) -> dict:
    raise HTTPException(status_code=501, detail="Not implemented")
