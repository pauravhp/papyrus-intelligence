"""
Two-step LLM scheduling chain using Groq.

Step 1 — enrich_tasks():     Assesses cognitive load, energy, and scheduling flags.
Step 2 — generate_schedule(): Assigns enriched tasks to free windows.

Both steps: JSON-only output, retry once on parse failure, log full prompt
on second failure per CLAUDE.md Rule 6.

Prompt construction lives in src/prompts/enrich.py and src/prompts/schedule.py.
"""

import json
import re

from groq import Groq

from src.models import FreeWindow, TodoistTask
from src.prompts.enrich import build_enrich_prompt
from src.prompts.schedule import build_schedule_prompt

ENRICH_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
SCHEDULE_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


# ── JSON helpers ───────────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Strip markdown fences and any preamble text, leaving raw JSON."""
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()
    if text and text[0] not in "{[":
        for i, ch in enumerate(text):
            if ch in "{[":
                text = text[i:]
                break
    return text.strip()


def _groq_json_call(
    client: Groq,
    model: str,
    messages: list[dict],
    description: str,
) -> dict | list:
    """
    Call Groq expecting a JSON response. Retries once on parse failure.
    Logs full prompt + raw response if both attempts fail, then raises.
    """
    last_content: str = ""
    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=4096,
            )
            last_content = response.choices[0].message.content or ""
            cleaned = _extract_json(last_content)
            return json.loads(cleaned)

        except json.JSONDecodeError as exc:
            if attempt < 2:
                print(
                    f"[LLM] Attempt 1 JSON parse failed for '{description}' — retrying…"
                )
                continue
            print(f"\n[LLM] CRITICAL: both attempts failed for '{description}'")
            print(f"[LLM] ── FULL PROMPT ──\n{json.dumps(messages, indent=2)}")
            print(f"[LLM] ── RAW RESPONSE ──\n{last_content}")
            raise RuntimeError(
                f"LLM returned invalid JSON for '{description}' after 2 attempts: {exc}"
            ) from exc

    raise RuntimeError("Unexpected exit from _groq_json_call")


# ── Step 1 — Enrich ────────────────────────────────────────────────────────────


def enrich_tasks(
    tasks: list[TodoistTask],
    context: dict,
    productivity_science: dict,
) -> list[dict]:
    """
    Step 1: Enrich each task with cognitive load, energy requirement, and scheduling flags.
    Returns a list of enrichment dicts (one per task, same order as input).
    Falls back to sensible defaults for any task the LLM omits.
    """
    if not tasks:
        return []

    client = Groq()
    messages = build_enrich_prompt(tasks, context, productivity_science)
    raw = _groq_json_call(client, ENRICH_MODEL, messages, "enrich_tasks")

    if isinstance(raw, dict):
        for key in ("tasks", "enriched_tasks", "results", "data"):
            if key in raw and isinstance(raw[key], list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise RuntimeError(f"enrich_tasks expected a JSON array, got {type(raw)}")

    enriched_map = {
        item.get("task_id", ""): item for item in raw if isinstance(item, dict)
    }

    result = []
    for t in tasks:
        if t.id in enriched_map:
            result.append(enriched_map[t.id])
        else:
            is_waiting = "waiting" in t.labels
            result.append(
                {
                    "task_id": t.id,
                    "cognitive_load": "medium",
                    "energy_requirement": "moderate",
                    "suggested_block": "afternoon",
                    "can_be_split": False,
                    "scheduling_flags": ["never-schedule"] if is_waiting else [],
                }
            )

    return result


# ── Step 2 — Schedule ──────────────────────────────────────────────────────────


def generate_schedule(
    enriched_tasks: list[dict],
    free_windows: list[FreeWindow],
    context: dict,
    heuristics_summary: dict,
    target_date: str,
) -> dict:
    """
    Step 2: Decide task order and session durations.
    Returns a dict with keys: reasoning_summary, ordered_tasks[], pushed[], flagged[].
    Clock-time assignment is handled separately by pack_schedule() in scheduler.py.
    """
    if not enriched_tasks or not free_windows:
        return {
            "reasoning_summary": "No tasks or no free windows — nothing to schedule.",
            "ordered_tasks": [],
            "pushed": [],
            "flagged": [],
        }

    client = Groq()
    messages = build_schedule_prompt(
        enriched_tasks, free_windows, context, heuristics_summary, target_date
    )
    raw = _groq_json_call(client, SCHEDULE_MODEL, messages, "generate_schedule")

    if not isinstance(raw, dict):
        raise RuntimeError(f"generate_schedule expected a JSON object, got {type(raw)}")

    for key in ("reasoning_summary", "ordered_tasks", "pushed", "flagged"):
        raw.setdefault(key, [] if key != "reasoning_summary" else "")

    return raw
