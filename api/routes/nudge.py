"""
POST /api/nudge/dismiss  — record a nudge dismissal

Per-instance dismiss: pass instance_key (e.g. task_id).
Per-type dismiss:     omit instance_key (stored as '__type__' sentinel).
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase

router = APIRouter()


class DismissPayload(BaseModel):
    nudge_type: str
    instance_key: Optional[str] = None
    mode: str = "forever"


@router.post("/api/nudge/dismiss")
def dismiss_nudge(
    payload: DismissPayload,
    user: dict = Depends(get_current_user),
) -> dict:
    # Use sentinel for per-type dismissals to avoid NULL UNIQUE issues
    key = payload.instance_key if payload.instance_key is not None else "__type__"

    supabase.from_("nudge_dismissals").upsert(
        {
            "user_id": user["sub"],
            "nudge_type": payload.nudge_type,
            "instance_key": key,
            "mode": payload.mode,
        },
        on_conflict="user_id,nudge_type,instance_key",
    ).execute()

    return {"ok": True}
