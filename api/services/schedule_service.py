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
SYSTEM_PROMPT = """You place tasks into the user's available time windows. Your only job is placement — constraints have already been applied to the windows by an earlier step, so anything outside the SUGGESTED WINDOWS is unavailable.

Reply ONLY with JSON in this exact shape:
{"scheduled":[{"task_id":"","task_name":"","start_time":"","end_time":"","duration_minutes":0,"category":""}],"pushed":[{"task_id":"","reason":""}],"reasoning_summary":""}

OUTPUT RULES
- start_time/end_time MUST be FULL ISO 8601 datetimes including DATE and UTC OFFSET — never time-only.
  CORRECT:   "2026-04-25T15:40:00-07:00"
  WRONG:     "15:40"     (no date, no offset)
  Take the date from the user message header and the UTC offset shown alongside the windows.
- Free window times in the user message are LOCAL — use them exactly, do NOT convert to UTC.
- For tasks that cross midnight (22:30 today → 02:30 tomorrow), end_time uses the NEXT day's date: "2026-04-26T02:30:00-07:00".
- Every task appears in exactly one list. Tasks that don't fit go in pushed.
- NEVER shorten a task's duration_minutes. If a task can't fit one contiguous slot, SPLIT across the next available window: same task_id, append " (pt 1)" / " (pt 2)" to task_name, parts sum to the original duration. If even split won't work, push the whole task — do not place a partial.
- Rhythm tasks (marked [rhythm]) accept any duration within the shown range. Treat their priority like one-off tasks.
- category: "deep_work" (focused concentration — writing, coding, design, research, analysis) or "admin" (lightweight — email, reviews, calls, admin). null if genuinely ambiguous. On a refinement, do not change a task's category from the previous proposal unless that task itself was replaced.

REASONING_SUMMARY RULES
- ONE or TWO short sentences in second person ("you"/"your"). Coach voice. Conversational.
- ABSOLUTELY NO NUMBERS attached to a time unit. Banned tokens include but are not limited to: "220-minute", "90-min", "135m", "3 hours", "2hr", "45 minutes", "1.5h", "an X-minute window". If you are about to write a digit followed (with or without a space or hyphen) by m, min, mins, minute(s), h, hr, hrs, or hour(s) — REWRITE THE SENTENCE WITHOUT THE NUMBER. Use "the window", "the morning", "your remaining time" instead.
- FORBIDDEN tokens: task IDs, priority codes (p1/p2/p3/p4), the literal JSON labels "deep_work" or "admin" (refer to them as "deep work" / "admin tasks" instead), arithmetic ("30m + 60m"), restating the current time, restating the cutoff, the words "the user", "hard rule", "soft block", "suggested window".
- The Python layer SCRUBS this field if it contains any banned numeric-duration token or JSON label — your summary will be replaced with an empty string and the user sees nothing. Treat that as a hard failure and avoid it.
- Refer to tasks by their human name (or omit the name).

PUSHED.REASON RULES
- Reference observable facts only: "didn't fit before your cutoff", "calendar conflict at 3pm", "no duration estimate set", "no contiguous slot available".
- NEVER invent user intent. Phrases like "deprioritized per your guidance", "as you requested", "to align with your goals" are forbidden unless the user literally used those words.

REFINEMENT RULES
- When the user note describes a TARGETED edit ("move X to 7am", "drop Y"), make the smallest changes needed and don't move/rearrange unrelated tasks.
- Treat the previous proposal in the user message as the baseline; small refinement is a diff.
- EXCEPTION — PRIORITY SHIFT: if the user explicitly elevates a task's priority or scope ("X for the entirety of today", "make X my main focus", "most of the day on X", "I really need to get X done", "X is the priority"), DISPLACE other tasks to make room for X. The previous proposal is no longer the baseline — treat the request as a new top priority for the day. Push the displaced tasks with reason "displaced by the priority you set this turn".
- Do NOT change a task's category from the previous proposal unless the task itself was replaced. The previous baseline shows each task's category; preserve it.

GOOD examples
- reasoning_summary: "Stacked your focus blocks into the late-night window before your cutoff, with a buffer if you need it."
- reasoning_summary: "Front-loaded the deep work this morning so admin tasks fall into the lower-energy afternoon."
- pushed.reason: "didn't fit before your cutoff today"
- pushed.reason: "no contiguous slot available"

BAD examples (do NOT produce these)
- reasoning_summary: "Scheduled 6gJjJ7M3 (60m, p2, deep_work) totaling 5.5h." (forbidden: IDs, p-codes, categories, totals)
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
            # The hint is structured (not embedded in content) so it survives
            # truncation and never leaks into user-facing task_name.
            hint = f" [hint: {t.rhythm_hint}]" if t.rhythm_hint else ""
            lines.append(f"{t.id} {t.content[:50]} p{t.priority} {dur_str}{cadence}{hint} [rhythm]")
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

    # Free windows must include date hints when they spill onto the next day —
    # otherwise the LLM defaults to target_date and emits 00:30 of the WRONG day.
    # Caught on 2026-04-25: cutoff_override extended to 03:30 next day, windows
    # showed "00:30–03:30" with no date qualifier, scheduler placed task at
    # 2026-04-25T00:30 (yesterday morning) instead of 2026-04-26T00:30.
    from datetime import date as _date, timedelta as _timedelta
    target_date_obj = _date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    next_day = (target_date_obj + _timedelta(days=1)).isoformat()

    def _format_window(w):
        s_next = w.start.date() > target_date_obj
        e_next = w.end.date() > target_date_obj
        s, e = w.start.strftime('%H:%M'), w.end.strftime('%H:%M')
        if s_next and e_next:
            label = f"{s}–{e} (entire window on NEXT DAY)"
        elif e_next:
            label = f"{s}–{e} (crosses midnight; end is NEXT DAY)"
        else:
            label = f"{s}–{e}"
        return f"{label} (UTC{tz_offset}, {w.duration_minutes}m)"

    windows_text = " | ".join(_format_window(w) for w in free_windows)
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

TASKS (id name priority duration [deadline]):
{tasks_text}

SUGGESTED WINDOWS (LOCAL, UTC{tz_offset}): {windows_text}
{calendar_section}
SOFT BLOCKS (preferred reserved time — use judgment):
{reserved_text}

HARD RULES (in addition to system rules):
{rules_text}
- Never schedule over a CALENDAR EVENT above.
- Do NOT invent break/recovery/filler tasks for gaps. Leave gaps empty.

DATETIME FORMAT FOR YOUR OUTPUT (do not deviate):
- Today's date is {target_date}. UTC offset is {tz_offset}. The NEXT DAY's date is {next_day}.
- For windows shown WITHOUT a "NEXT DAY" marker, use {target_date} as the date:
    A 15:40 placement → "{target_date}T15:40:00{tz_offset}"
- For windows marked "(crosses midnight; end is NEXT DAY)", times before midnight use {target_date}, times after midnight use {next_day}:
    A placement starting 22:30 today and ending 02:30 next day →
      start_time="{target_date}T22:30:00{tz_offset}", end_time="{next_day}T02:30:00{tz_offset}"
- For windows marked "(entire window on NEXT DAY)", BOTH start and end use {next_day}:
    A placement at 00:30–02:30 in such a window →
      start_time="{next_day}T00:30:00{tz_offset}", end_time="{next_day}T02:30:00{tz_offset}"
- This is the most common error mode: do NOT use {target_date} for a placement when the window says NEXT DAY. Use {next_day}.

GUIDANCE
- Prefer scheduling within the suggested windows.
- Leave at least {min_gap} minutes between consecutive deep_work tasks.
- If a task has a deadline within 48 hours of {target_date}, treat it as effectively P1 even if its Todoist priority says P2 or P3 — urgency overrides nominal priority.
- Rhythms (marked [rhythm]) are recurring commitments the user has explicitly opted into. When a rhythm and a P3 or P4 one-off task compete for the same window, PLACE THE RHYTHM. Only displace a rhythm with a P1/P2 task that has no other workable window. If a rhythm fits in any free window today, it should be placed before P3/P4 tasks fill that window.
- {_overflow_rule(config)}"""


# Patterns that indicate the LLM leaked internal scheduler state into the
# coach-voice reasoning_summary. Detection-only: if any pattern hits, the
# whole summary is dropped (replaced with ""), since stripping the offending
# phrase usually leaves a sentence fragment that reads worse than nothing.
#
# POLICY (2026-04-28): only ONE pattern, the digit+time-unit anchor. This is
# the real bug being defended against — Haiku sometimes leaks "the 220-minute
# window" or "stacked 135m of work" into the coach voice, which is internal
# scheduler arithmetic users shouldn't see.
#
# Earlier revisions also matched priority codes (p1/P2) and the underscore
# JSON token (deep_work). Both were too aggressive: "p1" and "p2" routinely
# appear in legitimate coach copy ("front-loaded your p1 task") and dropping
# the entire summary on that match left users staring at an empty panel.
# DO NOT re-add those patterns without a regression-passing test that proves
# the new pattern does not eat phrasings like the ones in
# `test_sanitize_reasoning_summary_passes_clean_coach_text`.
_REASONING_LEAK_PATTERNS = [
    # digit + optional sep + time-unit suffix
    re.compile(r"\b\d+(?:\.\d+)?\s*[-]?\s*(?:m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", re.IGNORECASE),
]


def _sanitize_reasoning_summary(text: str) -> str:
    """Drop the summary if it contains a leaked internal phrasing. Returns
    the original text when clean. The frontend tolerates an empty string."""
    if not text:
        return text
    for pat in _REASONING_LEAK_PATTERNS:
        if pat.search(text):
            return ""
    return text


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
    result["reasoning_summary"] = _sanitize_reasoning_summary(result["reasoning_summary"])
    result["pushed"].extend(no_duration_pushed)
    return result
