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
from src.llm import _extract_json, _groq_json_call
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
            try:
                encrypted = supabase.rpc(
                    "encrypt_field", {"plaintext": value.strip()}
                ).execute().data
            except Exception:
                raise HTTPException(status_code=503, detail="credential store unavailable")
            updates[field] = encrypted

    if updates:
        try:
            supabase.from_("users").update(updates).eq("id", user_id).execute()
        except Exception:
            raise HTTPException(status_code=503, detail="credential store unavailable")

    return SaveCredentialsResponse(success=True)


# ── scan ──────────────────────────────────────────────────────────────────────


class ScanRequest(BaseModel):
    timezone: str
    calendar_ids: list[str] = []


class ScanResponse(BaseModel):
    proposed_config: dict
    questions: list


def _decrypt_key(enc: str | None) -> str | None:
    """Decrypt a single field from Supabase. Returns None if enc is None/empty."""
    if not enc:
        return None
    try:
        return supabase.rpc("decrypt_field", {"ciphertext": enc}).execute().data
    except Exception:
        return None


def _llm_json_call_onboard(
    messages: list[dict],
    description: str,
    groq_key: str | None,
    anthropic_key: str | None,
) -> dict:
    """Call LLM for JSON output. Prefers Groq; falls back to Anthropic."""
    if groq_key:
        groq_client = Groq(api_key=groq_key)
        return _groq_json_call(groq_client, ONBOARD_MODEL, messages, description)
    elif anthropic_key:
        import anthropic as ant

        client = ant.Anthropic(api_key=anthropic_key)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        last_content: str = ""
        for attempt in range(1, 3):
            try:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=4096,
                    system=system,
                    messages=user_msgs,
                )
                last_content = resp.content[0].text or ""
                cleaned = _extract_json(last_content)
                return json.loads(cleaned)
            except json.JSONDecodeError:
                if attempt < 2:
                    print(
                        f"[LLM] Attempt 1 JSON parse failed for '{description}' (Anthropic) — retrying…"
                    )
                    continue
                print(f"\n[LLM] CRITICAL: both attempts failed for '{description}' (Anthropic)")
                print(f"[LLM] ── RAW RESPONSE ──\n{last_content}")
                raise
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No LLM API key configured. Complete setup and add a Groq or Anthropic key.",
    )


@router.post("/scan", response_model=ScanResponse)
def onboard_scan(
    body: ScanRequest,
    user: dict = Depends(get_current_user),
) -> ScanResponse:
    """
    Scan the last 14 days of Google Calendar to propose a schedule config.
    Reads google_credentials + LLM key from Supabase — no secrets in the request body.
    """
    user_id: str = user["sub"]

    row_result = (
        supabase.from_("users")
        .select("google_credentials, groq_api_key, anthropic_api_key")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row_result.data:
        raise HTTPException(status_code=400, detail="User not found.")

    row = row_result.data
    creds_data: dict | None = row.get("google_credentials")
    if not creds_data:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected. Complete OAuth at /auth/google first.",
        )

    set_encryption_key()
    groq_key = _decrypt_key(row.get("groq_api_key"))
    anthropic_key = _decrypt_key(row.get("anthropic_api_key"))

    if not groq_key and not anthropic_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key found. Re-run setup and provide a Groq or Anthropic key.",
        )

    # Build GCal service
    try:
        gcal_service, refreshed = build_gcal_service_from_credentials(
            creds_data, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        )
        if refreshed:
            supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"GCal token invalid: {exc}")

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
                extra_calendar_ids=body.calendar_ids,
                service=gcal_service,
            )
            events_by_date[target] = day_events
            all_events.extend(day_events)
        except Exception as exc:
            print(f"[onboard/scan] Warning: could not fetch {target}: {exc}")
            events_by_date[target] = []

    patterns = build_pattern_summary(events_by_date, all_events)
    messages = build_onboard_prompt(patterns, context_for_prompt)

    try:
        raw = _llm_json_call_onboard(messages, "onboard_scan", groq_key, anthropic_key)
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="Unexpected LLM response shape.")

    return ScanResponse(
        proposed_config=raw.get("proposed_config") or {},
        questions=raw.get("questions_for_stage_2") or [],
    )


# ── promote ───────────────────────────────────────────────────────────────────


class PromoteRequest(BaseModel):
    config: dict


class PromoteResponse(BaseModel):
    success: bool


@router.post("/promote", response_model=PromoteResponse)
def onboard_promote(
    body: PromoteRequest,
    user: dict = Depends(get_current_user),
) -> PromoteResponse:
    """
    Save the confirmed config to users.config.
    Credentials are already in Supabase from save-credentials — not accepted here.
    """
    user_id: str = user["sub"]

    clean = copy.deepcopy(body.config)
    clean.pop("_onboard_draft", None)

    try:
        supabase.from_("users").update({"config": clean}).eq("id", user_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Supabase write failed: {exc}")

    return PromoteResponse(success=True)
