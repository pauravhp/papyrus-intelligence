"""
schedule_day() — single LLM call for scheduling (CLAUDE.md Rule 4).

Input:  tasks + free windows + config + context_note
Output: {scheduled: [...], pushed: [...], reasoning_summary: "..."}

Primary: Anthropic SDK (claude-haiku-4-5-20251001)
Fallback: Groq (meta-llama/llama-4-scout-17b-16e-instruct)

JSON validation: retry once on parse failure; raise RuntimeError on second failure.
"""

import json
import re
from datetime import date

import anthropic
from groq import Groq

from src.models import FreeWindow, TodoistTask

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _build_prompt(
    tasks: list[TodoistTask],
    free_windows: list[FreeWindow],
    config: dict,
    context_note: str,
    target_date: str,
) -> str:
    tz = config.get("user", {}).get("timezone", "UTC")
    rules_hard = config.get("rules", {}).get("hard", [])

    lines = []
    for t in tasks:
        if t.is_rhythm and t.session_max_minutes:
            dur_str = f"{t.duration_minutes}-{t.session_max_minutes}min"
            cadence = f" [{t.sessions_per_week}x/week]" if t.sessions_per_week else ""
            lines.append(f"{t.id} {t.content[:50]} {dur_str}{cadence}")
        else:
            lines.append(
                f"{t.id} {t.content[:50]} p{t.priority} {t.duration_minutes}m"
                + (f" due={t.deadline}" if t.deadline else "")
            )
    tasks_text = "\n".join(lines)
    windows_text = " | ".join(
        f"{w.start.strftime('%H:%M')}-{w.end.strftime('%H:%M')}({w.duration_minutes}m)"
        for w in free_windows
    )
    rules_text = "\n".join(f"- {r}" for r in rules_hard) if rules_hard else "None"

    note = f"Note: {context_note}" if context_note else ""

    return f"""Schedule tasks for {target_date} tz={tz}. {note}

TASKS (id name priority duration):
{tasks_text}

FREE WINDOWS: {windows_text}

HARD RULES: {rules_text}

Reply ONLY with JSON:
{{"scheduled":[{{"task_id":"","task_name":"","start_time":"","end_time":"","duration_minutes":0}}],"pushed":[{{"task_id":"","reason":""}}],"reasoning_summary":""}}

- start_time/end_time: ISO 8601 with tz offset e.g. {target_date}T09:00:00-07:00
- Every task in exactly one list. Tasks that don't fit go in pushed.
- For rhythm tasks (id starts with proj_): pick any duration within the shown range (e.g. 120-180min means schedule between 120 and 180 minutes). The cadence [Nx/week] is informational — aim to include a rhythm session if there's room."""


def _extract_json(text: str) -> str:
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


def _parse_with_retry(raw_fn, description: str) -> dict:
    """Call raw_fn() twice; parse JSON; raise RuntimeError on second failure."""
    last_content = ""
    for attempt in range(1, 3):
        try:
            last_content = raw_fn()
            return json.loads(_extract_json(last_content))
        except json.JSONDecodeError:
            if attempt < 2:
                print(f"[schedule_day] Attempt 1 JSON parse failed for '{description}' — retrying…")
                continue
            print(f"[schedule_day] CRITICAL: both attempts failed for '{description}'")
            print(f"[schedule_day] RAW: {last_content}")
            raise RuntimeError(
                f"schedule_day returned invalid JSON for '{description}' after 2 attempts"
            )
    raise RuntimeError("Unexpected exit from _parse_with_retry")


def schedule_day(
    tasks: list[TodoistTask],
    free_windows: list[FreeWindow],
    config: dict,
    context_note: str,
    anthropic_api_key: str | None,
    groq_api_key: str | None,
    target_date: str | None = None,
) -> dict:
    """
    Single LLM call that assigns tasks to time slots.

    Returns:
        {
          "scheduled": [{"task_id", "task_name", "start_time", "end_time", "duration_minutes"}],
          "pushed":    [{"task_id", "reason"}],
          "reasoning_summary": "..."
        }
    """
    if not target_date:
        target_date = date.today().isoformat()

    prompt = _build_prompt(tasks, free_windows, config, context_note, target_date)

    if anthropic_api_key:
        client = anthropic.Anthropic(api_key=anthropic_api_key)

        def _call():
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2048,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text

        result = _parse_with_retry(_call, "schedule_day/anthropic")
    elif groq_api_key:
        groq_client = Groq(api_key=groq_api_key)

        def _call():  # type: ignore[misc]
            resp = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""

        result = _parse_with_retry(_call, "schedule_day/groq")
    else:
        import warnings
        warnings.warn("[schedule_day] No API key provided — returning empty schedule", stacklevel=2)
        return {"scheduled": [], "pushed": [], "reasoning_summary": "No LLM key available."}

    result.setdefault("scheduled", [])
    result.setdefault("pushed", [])
    result.setdefault("reasoning_summary", "")
    return result
