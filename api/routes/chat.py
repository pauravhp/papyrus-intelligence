"""
POST /api/chat — ReAct agent loop.

Request:
  {
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "context_note": ""   # optional override; agent can also pick it up from the message
  }

Response:
  {
    "message": "...",          # assistant's final text
    "schedule_card": {...},    # present if schedule_day was called this turn
    "messages": [...]          # updated conversation history
  }

Architecture:
- Stateless: full conversation history comes in with each request
- Tool loop: up to MAX_ITERATIONS Anthropic tool-use cycles
- Keys: loaded from Supabase when present; fall back to local env vars (dev only)
"""

import json
from datetime import date

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user
from api.db import supabase
from api.config import settings
from api.services.agent_tools import TOOL_SCHEMAS, TOOL_DISPATCH
from api.services import nudge_service
from api.services.nudge_service import NudgeCard
from src.calendar_client import build_gcal_service_from_credentials

router = APIRouter()
MAX_ITERATIONS = 10

SYSTEM_PROMPT = """You are Papyrus, a calm and effective scheduling coach.

Your job is to help the user plan their day, replan when things slip, and reflect on their week.

Available tools:
- get_date: resolve any date — offset_days=0 for today, 1 for tomorrow, 7 for next week. ALWAYS call this instead of asking the user for a date.
- get_tasks: fetch Todoist tasks. Only call when the user explicitly asks to see their task list.
- get_calendar: fetch Google Calendar events for a specific date (YYYY-MM-DD).
- get_rhythms: fetch active rhythms (recurring weekly commitments with session cadence). schedule_day injects these automatically — only call directly when the user asks about their rhythms.
- schedule_day: run the scheduling engine — pass target_date as YYYY-MM-DD. Fetches tasks and injects active rhythms internally. Always call before confirm_schedule.
- confirm_schedule: write schedule to GCal + Todoist. Only after explicit user approval.
- push_task: push a Todoist task to another day.
- get_status: check today's confirmed schedule.
- manage_rhythm: create/update/delete rhythm commitments via natural language (e.g. "add a 3x/week gym rhythm, 45–60 min").

Rules:
- Never ask the user for a date. Call get_date first.
- To plan a day: call get_date → schedule_day. schedule_day already fetches tasks and injects active rhythms.
- Never call confirm_schedule unless the user explicitly approves.
- Present schedules concisely: task name, time, duration.
- One coaching nudge max per conversation.
- Schedule results contain ISO 8601 timestamps with UTC offsets (e.g. "2026-04-16T09:15:00-07:00"). ALWAYS display times in the user's LOCAL time (use the wall-clock time from the timestamp, not UTC). For example, "2026-04-16T09:15:00-07:00" is 9:15 AM local — display it as "9:15 AM", never convert to UTC.
"""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context_note: str = ""


class ChatResponse(BaseModel):
    message: str
    schedule_card: dict | None = None
    nudge: NudgeCard | None = None
    messages: list[dict]


def _load_user_context(user_id: str) -> dict:
    """Load config + Todoist OAuth token + build GCal service from Supabase."""
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

    tod_token: str | None = (row.get("todoist_oauth_token") or {}).get("access_token")

    # Build GCal service
    gcal_creds = row.get("google_credentials")
    gcal_service = None
    if gcal_creds:
        try:
            svc, refreshed = build_gcal_service_from_credentials(
                gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
            )
            gcal_service = svc
            if refreshed:
                supabase.from_("users").update({"google_credentials": refreshed}).eq("id", user_id).execute()
        except Exception as exc:
            print(f"[chat] GCal service init failed: {exc}")

    return {
        "user_id": user_id,
        "config": config,
        "todoist_api_key": tod_token,   # kept as "todoist_api_key" — TodoistClient uses Bearer auth either way
        "gcal_service": gcal_service,
        "supabase": supabase,
        "anthropic_api_key": settings.ANTHROPIC_API_KEY,
    }


@router.post("/api/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
) -> ChatResponse:
    user_id: str = user["sub"]
    user_ctx = _load_user_context(user_id)

    # Evaluate nudge before the agent loop (first message only; mid-conversation guard inside)
    messages_raw = [{"role": m.role, "content": m.content} for m in body.messages]
    nudge_card = nudge_service.get_eligible(user_ctx, messages_raw)

    ant_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build system prompt — inject nudge if eligible
    system = SYSTEM_PROMPT
    if nudge_card:
        system += f"\n\nELIGIBLE_NUDGE: {nudge_card.model_dump_json()}"
        system += (
            "\n\nIf schedule_day was called in this response, include the nudge as a "
            "coaching observation AFTER your scheduling reasoning — before the user "
            "decides to confirm. Keep it to 2–3 sentences: the observation, one "
            "sentence of science, and the offer. Gain-framed only. "
            "Do not raise it again if the user dismisses or ignores it."
        )

    messages = messages_raw
    schedule_card: dict | None = None

    # Anthropic ReAct loop
    for _ in range(MAX_ITERATIONS):
        response = ant_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Collect assistant content
        assistant_blocks: list[dict] = []
        for block in response.content:
            if block.type == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_blocks})

        if response.stop_reason == "end_turn":
            final_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return ChatResponse(
                message=final_text,
                schedule_card=schedule_card,
                nudge=nudge_card,
                messages=messages,
            )

        if response.stop_reason != "tool_use":
            break

        # Execute tools
        tool_results: list[dict] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            dispatcher = TOOL_DISPATCH.get(tool_name)
            if not dispatcher:
                result_content = json.dumps({"error": f"unknown tool: {tool_name}"})
            else:
                try:
                    result = dispatcher(block.input, user_ctx)
                    if tool_name == "schedule_day":
                        schedule_card = result
                    result_content = json.dumps(result)
                except Exception as exc:
                    print(f"[chat] Tool {tool_name} failed: {exc}")
                    result_content = json.dumps({"error": str(exc)})

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_content,
            })

        messages.append({"role": "user", "content": tool_results})

    # Fallback if loop exhausted
    return ChatResponse(
        message="I ran into an issue completing your request. Please try again.",
        schedule_card=schedule_card,
        nudge=nudge_card,
        messages=messages,
    )
