# api/routes/onboard.py
"""
POST /api/onboard/save-credentials  — encrypt + store API keys immediately
POST /api/onboard/scan              — 14-day GCal scan → proposed config
POST /api/onboard/promote           — save final config to users.config
"""

import copy
import json
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from google.oauth2.credentials import Credentials
from groq import Groq
from pydantic import BaseModel

from api.auth import get_current_user
from api.config import settings
from api.db import set_encryption_key, supabase
from src.calendar_client import WRITE_SCOPES, build_gcal_service_from_credentials, get_events
from src.llm import _groq_json_call
from src.onboard_patterns import build_pattern_summary
from src.prompts.onboard import build_onboard_prompt

router = APIRouter(prefix="/api/onboard")

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "context.template.json"
ONBOARD_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DAYS_TO_SCAN = 14


# ── save-credentials ──────────────────────────────────────────────────────────


class SaveCredentialsRequest(BaseModel):
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    todoist_api_key: str = ""


class SaveCredentialsResponse(BaseModel):
    success: bool


@router.post("/save-credentials", response_model=SaveCredentialsResponse)
def save_credentials(
    body: SaveCredentialsRequest,
    user: dict = Depends(get_current_user),
) -> SaveCredentialsResponse:
    """
    Encrypt and store API keys in Supabase immediately.
    Called at the end of the Setup phase — before the GCal scan runs.
    Empty strings are skipped (key not provided by user).
    """
    user_id: str = user["sub"]
    set_encryption_key()

    updates: dict = {}
    for field, value in [
        ("groq_api_key", body.groq_api_key),
        ("anthropic_api_key", body.anthropic_api_key),
        ("todoist_api_key", body.todoist_api_key),
    ]:
        if value.strip():
            encrypted = supabase.rpc(
                "encrypt_field", {"plaintext": value.strip()}
            ).execute().data
            updates[field] = encrypted

    if updates:
        supabase.from_("users").update(updates).eq("id", user_id).execute()

    return SaveCredentialsResponse(success=True)
