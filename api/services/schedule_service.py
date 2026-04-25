"""
schedule_day() — single LLM call for scheduling (CLAUDE.md Rule 4).

Input:  tasks + free windows + config + context_note
Output: {scheduled: [...], pushed: [...], reasoning_summary: "..."}

Primary: Anthropic SDK (claude-haiku-4-5-20251001)

JSON validation: retry once on parse failure; raise RuntimeError on second failure.
"""

import json
import re
from datetime import date

import anthropic

from src.models import CalendarEvent, FreeWindow, TodoistTask

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Static system prompt — eligible for prompt caching since it never varies
# per request. Anthropic caches the prefix up to the cache_control marker;
# we mark this whole block ephemeral so subsequent calls within ~5 min
# read it back at 10% of normal input cost. Keep this string stable —
# any per-request data must live in the user message, never here.
SYSTEM_PROMPT = """You schedule tasks for a user across their available time windows.

Reply ONLY with JSON in this exact shape:
{"scheduled":[{"task_id":"","task_name":"","start_time":"","end_time":"","duration_minutes":0,"category":""}],"pushed":[{"task_id":"","reason":""}],"reasoning_summary":""}

OUTPUT RULES
- start_time/end_time: ISO 8601 with the user's UTC offset shown in the user message.
- Free window times in the user message are LOCAL — use them exactly, do NOT convert to UTC.
- Every task appears in exactly one list. Tasks that don't fit go in pushed.
- NEVER shorten a task's duration_minutes. If a task can't fit one contiguous slot, SPLIT across the next available window: same task_id, append " (pt 1)" / " (pt 2)" to task_name, parts sum to the original duration.
- Rhythm tasks (marked [rhythm]) accept any duration within the shown range. Treat their priority like one-off tasks.
- category: "deep_work" (focused concentration — writing, coding, design, research, analysis) or "admin" (lightweight — email, reviews, calls, admin). null if genuinely ambiguous.

REASONING_SUMMARY RULES
- ONE or TWO short sentences in second person ("you"/"your"). Coach voice. Conversational.
- FORBIDDEN in this field: task IDs, priority codes (p1/p2/p3/p4), category labels (deep_work/admin), arithmetic ("30m + 60m"), hour totals or duration totals of any kind, restating the current time, restating the cutoff, the words "the user", "hard rule", "soft block", "suggested window".
- Refer to tasks by their human name (or omit the name).

PUSHED.REASON RULES
- Reference observable facts only: "didn't fit before your cutoff", "calendar conflict at 3pm", "you blocked this time", "no duration estimate set".
- NEVER invent user intent. Phrases like "deprioritized per your guidance", "as you requested", "to align with your goals" are forbidden unless the user literally used those words in the context note.

REFINEMENT RULES
- When the context note describes an EDIT to an existing plan ("move X to 7am", "give Y more time", "drop Z"), make the smallest changes needed to satisfy that edit.
- Do NOT move, split, drop, or rearrange tasks unrelated to the user's ask.
- Treat the user's previous proposal as the baseline; refinement is a diff, not a fresh plan.

USER-STATED CONSTRAINTS IN CONTEXT NOTE
- If the context note contains a time block ("block 4pm-9pm", "I have an event 14:00-15:30", "no calls after 5pm", "free until noon"), treat it as a HARD RULE — equivalent to a calendar event. Never schedule over it.
- These constraints persist within a refinement chain; do not relax them on later turns unless the user explicitly removes them.

GOOD examples
- reasoning_summary: "Stacked your focus blocks into the late-night window before your cutoff, with a 30-min buffer if you need it."
- reasoning_summary: "Front-loaded the deep work this morning so admin tasks fall into the lower-energy afternoon."
- pushed.reason: "didn't fit before your cutoff today"
- pushed.reason: "you blocked 4pm-9pm"

BAD examples (do NOT produce these)
- reasoning_summary: "Current time is 03:23. The user wants larger blocks. Scheduled 6gJjJ7M3 (60m, p2, deep_work) totaling 5.5h." (forbidden: time, third-person, IDs, p-codes, categories, totals)
- reasoning_summary: "I scheduled 4 tasks adding to 135m before your 02:30 cutoff." (forbidden: arithmetic, restated cutoff)
- pushed.reason: "Deprioritized per your guidance" (forbidden: invented intent)"""


def _overflow_rule(config: dict) -> str:
    """
    Build the end-of-day overflow instruction.

    If the user has explicitly set sleep.no_tasks_after in their config,
    treat it as a hard cutoff and push overflow to another day. Otherwise
    (default 23:00 is implicit), allow overflow into late-night hours
    since the user hasn't signalled they want a firm boundary. Either
    way, shorter overflows within non-end-of-day gaps (between events,
    over soft meal blocks) remain at the LLM's discretion.
    """
    sleep = config.get("sleep") or {}
    user_set_cutoff = "no_tasks_after" in sleep
    if user_set_cutoff:
        cutoff = sleep.get("no_tasks_after")
        return (
            f"The user has set a hard end-of-day cutoff at {cutoff}. Never schedule any task that starts or ends "
            "past this time — the SUGGESTED WINDOWS already reflect it. If tasks don't fit today within that boundary, "
            "push them to another day. You may still overflow slightly within the day (e.g. across a soft meal block, "
            "or fitting a task right up against the cutoff) when priority warrants it."
        )
    return (
        "If tasks don't fit within suggested windows, you may schedule outside them (including late-night hours) "
        "rather than push tasks — use judgment based on task priority and the user's note."
    )


def _build_prompt(
    tasks: list[TodoistTask],
    free_windows: list[FreeWindow],
    config: dict,
    context_note: str,
    target_date: str,
    events: list[CalendarEvent] | None = None,
) -> str:
    tz = config.get("user", {}).get("timezone", "UTC")
    rules_hard = config.get("rules", {}).get("hard", [])

    lines = []
    for t in tasks:
        if t.is_rhythm and t.session_max_minutes:
            dur_str = f"{t.duration_minutes}-{t.session_max_minutes}min"
            cadence = f" [{t.sessions_per_week}x/week]" if t.sessions_per_week else ""
            lines.append(f"{t.id} {t.content[:50]} p{t.priority} {dur_str}{cadence} [rhythm]")
        else:
            lines.append(
                f"{t.id} {t.content[:50]} p{t.priority} {t.duration_minutes}m"
                + (f" due={t.deadline}" if t.deadline else "")
            )
    tasks_text = "\n".join(lines)

    # Derive the real UTC offset from the free windows so the LLM never has to guess.
    # Format: "+HH:MM" or "-HH:MM" (ISO 8601 offset notation)
    if free_windows:
        raw_offset = free_windows[0].start.strftime("%z")  # e.g. "-0700"
        tz_offset = f"{raw_offset[:3]}:{raw_offset[3:]}" if len(raw_offset) == 5 else raw_offset
    else:
        tz_offset = "+00:00"

    windows_text = " | ".join(
        f"{w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')} (UTC{tz_offset}, {w.duration_minutes}m)"
        for w in free_windows
    )
    rules_text = "\n".join(f"- {r}" for r in rules_hard) if rules_hard else "None"

    # Min gap between tasks
    min_gap = config.get("scheduling", {}).get("min_gap_between_tasks_minutes", 10)

    # Meal / daily blocks — already excluded from free windows; listed here so the LLM
    # knows WHY those windows are missing and does not invent "break" tasks to fill them.
    daily_blocks = config.get("daily_blocks", [])
    if daily_blocks:
        reserved_text = ", ".join(
            f"{db['name']} {db['start']}–{db['end']}" for db in daily_blocks
        )
    else:
        reserved_text = "Lunch 12:30–13:30, Dinner 19:00–20:00"

    note = f"Note: {context_note}" if context_note else ""

    timed_events = [e for e in (events or []) if not e.is_all_day]
    if timed_events:
        events_lines = "\n".join(
            f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')} {e.summary}"
            for e in sorted(timed_events, key=lambda e: e.start)
        )
        calendar_section = f"\nCALENDAR EVENTS (already blocked — do not schedule over these):\n{events_lines}\n"
    else:
        calendar_section = ""

    return f"""Schedule tasks for {target_date} (timezone {tz}, UTC{tz_offset}).{(' ' + note) if note else ''}

TASKS (id name priority duration):
{tasks_text}

SUGGESTED WINDOWS (LOCAL, UTC{tz_offset}): {windows_text}
{calendar_section}
SOFT BLOCKS (preferred reserved time — use judgment):
{reserved_text}

HARD RULES (in addition to system rules):
{rules_text}
- Never schedule over a CALENDAR EVENT above.
- Do NOT invent break/recovery/filler tasks for gaps. Leave gaps empty.

GUIDANCE
- Prefer scheduling within the suggested windows.
- Leave at least {min_gap} minutes between consecutive deep_work tasks.
- {_overflow_rule(config)}"""


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
            print(f"[schedule_day] raw LLM response (attempt {attempt}):\n{last_content}")
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
    target_date: str | None = None,
    events: list[CalendarEvent] | None = None,
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

    # Pre-filter tasks without a duration estimate. The LLM cannot place them
    # and previously rendered them as "Nonem" in the prompt, then bloated the
    # response by listing each in `pushed`. Surface them with an actionable
    # reason and keep them out of the LLM input entirely.
    schedulable_tasks = [t for t in tasks if t.duration_minutes is not None]
    no_duration_pushed = [
        {"task_id": t.id, "reason": "No duration estimate set in Todoist — add one to schedule it."}
        for t in tasks
        if t.duration_minutes is None
    ]

    prompt = _build_prompt(schedulable_tasks, free_windows, config, context_note, target_date, events=events)

    if anthropic_api_key:
        client = anthropic.Anthropic(api_key=anthropic_api_key)

        def _call():
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                temperature=0.2,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text

        result = _parse_with_retry(_call, "schedule_day/anthropic")
    else:
        import warnings
        warnings.warn("[schedule_day] No API key provided — returning empty schedule", stacklevel=2)
        return {
            "scheduled": [],
            "pushed": no_duration_pushed,
            "reasoning_summary": "No LLM key available.",
        }

    result.setdefault("scheduled", [])
    result.setdefault("pushed", [])
    result.setdefault("reasoning_summary", "")
    result["pushed"].extend(no_duration_pushed)
    return result
