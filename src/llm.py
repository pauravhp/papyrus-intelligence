"""
Two-step LLM scheduling chain using Groq.

Step 1 — enrich_tasks():   llama-3.3-70b-versatile
  Assesses cognitive load, energy requirement, and scheduling flags per task.

Step 2 — generate_schedule():  llama-3.3-70b-versatile
  Assigns enriched tasks to free windows using productivity science reasoning.

Both steps: JSON-only output, retry once on parse failure, log full prompt
on second failure per CLAUDE.md Rule 6.
"""

import json
import re
from datetime import datetime

from groq import Groq

from src.models import FreeWindow, TodoistTask

ENRICH_MODEL = "llama-3.3-70b-versatile"
SCHEDULE_MODEL = "llama-3.3-70b-versatile"

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Strip markdown fences and any preamble text, leaving raw JSON."""
    text = text.strip()
    # Strip opening/closing ``` fences
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()
    # If preamble precedes the JSON object/array, skip to the first { or [
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
            # Both attempts failed
            print(f"\n[LLM] CRITICAL: both attempts failed for '{description}'")
            print(f"[LLM] ── FULL PROMPT ──\n{json.dumps(messages, indent=2)}")
            print(f"[LLM] ── RAW RESPONSE ──\n{last_content}")
            raise RuntimeError(
                f"LLM returned invalid JSON for '{description}' after 2 attempts: {exc}"
            ) from exc

    # Unreachable, but satisfies type checker
    raise RuntimeError("Unexpected exit from _groq_json_call")


# ── Step 1 — Enrich ────────────────────────────────────────────────────────────


def _build_enrich_prompt(
    tasks: list[TodoistTask],
    context: dict,
    productivity_science: dict,
) -> list[dict]:
    label_vocab = context.get("label_vocabulary", {})

    task_list = []
    for t in tasks:
        # Todoist API priority 1 = P4 (default/unset). Mark these clearly so the
        # model knows to suggest a priority for them.
        priority_str = _PRIORITY_LABEL.get(t.priority, "P4")
        if t.priority == 1:
            priority_str = "P4 (unset)"
        task_list.append(
            {
                "task_id": t.id,
                "content": t.content,
                "priority": priority_str,
                "duration_minutes": t.duration_minutes,
                "labels": t.labels,
                "deadline": t.deadline,
            }
        )

    system = (
        "You are a scheduling assistant. Your job is to analyze tasks and assess "
        "their cognitive and scheduling properties. You respond ONLY with valid JSON. "
        "No markdown. No explanations. No text outside the JSON."
    )

    user = f"""## Task: Enrich Each Task for Scheduling

You will be given a list of tasks. For EACH task, output one enrichment object.

---

## Label Vocabulary (these are hard scheduling constraints)
{json.dumps(label_vocab, indent=2)}

---

## Productivity Research Reference
Use the research below to inform your assessments of cognitive_load and energy_requirement.

{json.dumps(productivity_science, indent=2)}

---

## Tasks to Enrich
{json.dumps(task_list, indent=2)}

---

## Output Format
Return a JSON ARRAY. One object per task, in the SAME ORDER as the input list.

Base fields — required for EVERY task:

{{
  "task_id": "<string — copy exactly from input>",
  "cognitive_load": "<high | medium | low>",
  "energy_requirement": "<peak | moderate | low>",
  "suggested_block": "<descriptive string, e.g. morning peak focus>",
  "can_be_split": <true | false>,
  "scheduling_flags": ["<string>", ...]
}}

Additional fields — required ONLY for tasks whose priority is "P4 (unset)":

{{
  "suggested_priority": "<P1 | P2 | P3 | P4>",
  "suggested_priority_reason": "<one-line reason — consider task name, any deadline, project context, urgency>"
}}

Do NOT include suggested_priority or suggested_priority_reason for tasks that already
have an explicit priority (P1, P2, or P3).

Rules for base fields:
- cognitive_load "high" = novel thinking, synthesis, creation, debugging
- cognitive_load "medium" = editing, reviewing, moderate problem solving
- cognitive_load "low" = admin, filing, routine correspondence
- energy_requirement "peak" = requires morning peak window
- energy_requirement "moderate" = afternoon secondary peak is fine
- energy_requirement "low" = can be done during trough
- scheduling_flags: include any of ["needs-deep-work-block", "batch-with-admin",
  "never-schedule" (for @waiting tasks), "high-urgency", "at-risk", "quick-task"]

Return ONLY the JSON array. No markdown. No backticks. No explanation."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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
    messages = _build_enrich_prompt(tasks, context, productivity_science)
    raw = _groq_json_call(client, ENRICH_MODEL, messages, "enrich_tasks")

    # Normalise: accept both a bare list and {"tasks": [...]} wrapper
    if isinstance(raw, dict):
        for key in ("tasks", "enriched_tasks", "results", "data"):
            if key in raw and isinstance(raw[key], list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise RuntimeError(f"enrich_tasks expected a JSON array, got {type(raw)}")

    # Index by task_id
    enriched_map = {
        item.get("task_id", ""): item for item in raw if isinstance(item, dict)
    }

    # Build final list in original task order; supply defaults for missing tasks
    result = []
    for t in tasks:
        if t.id in enriched_map:
            result.append(enriched_map[t.id])
        else:
            # LLM omitted this task — apply safe defaults
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


def _format_windows(windows: list[FreeWindow]) -> dict:
    """Format windows for the LLM — block type and duration only, no clock times.
    The LLM decides task order; Python handles all time arithmetic in pack_schedule().
    """
    return {
        "total_available_minutes": sum(w.duration_minutes for w in windows),
        "windows": [
            {
                "window_index": i,
                "block_type": w.block_type,
                "duration_minutes": w.duration_minutes,
            }
            for i, w in enumerate(windows)
        ],
    }


def _build_schedule_prompt(
    enriched_tasks: list[dict],
    free_windows: list[FreeWindow],
    context: dict,
    heuristics_summary: dict,
    target_date: str,
) -> list[dict]:
    rules = context.get("rules_plaintext", [])

    system = (
        "You are a scheduling assistant. You decide the ORDER of tasks and their "
        "session durations using productivity science. You respond ONLY with valid JSON. "
        "No markdown. No backticks. No text outside the JSON object."
    )

    user = f"""## Task: Generate Schedule Order for {target_date}

Your job is to decide the ORDER tasks should be done and how long each session should be.
Do NOT output any clock times — times will be computed separately by the system.

---

## Scheduling Heuristics (from productivity research)
{json.dumps(heuristics_summary, indent=2)}

---

## Hard Rules — NEVER VIOLATE THESE
{json.dumps(rules, indent=2)}

---

## Available Free Windows (block types and durations — no clock times)
{json.dumps(_format_windows(free_windows), indent=2)}

---

## Enriched Tasks (to be ordered and scheduled or pushed)
{json.dumps(enriched_tasks, indent=2)}

---

## Instructions

### Priority ordering — ABSOLUTE RULE, no exceptions
Order ALL P1 tasks before ANY P2 task. ALL P2 before ANY P3. ALL P3 before ANY P4.
Within the same priority level, use cognitive load and window type to break ties.
A P2 task MUST NOT appear before a P1 task in ordered_tasks under any circumstances.

### What goes in ordered_tasks
Put EVERY task here EXCEPT those with "never-schedule" in scheduling_flags.
Do NOT push tasks because you think they might not fit — pack_schedule handles
overflow. Your only job is to ORDER them. If in doubt, include it.
   - Match tasks to window types (e.g. deep-work tasks → morning, admin → afternoon).
   - duration_minutes must not exceed the task's original duration_minutes.
   - Set can_be_split: true only if the task can genuinely resume after a break.
   - break_after_minutes: 0 unless a specific transition benefit justifies a break.

### What goes in pushed
ONLY tasks with "never-schedule" in scheduling_flags (i.e. @waiting tasks).
Do NOT push tasks for capacity reasons — that is not your decision to make.

### Flagged
Flag tasks that are overdue P1 or have been rescheduled 3+ times.

### placement_reason
Cite the specific productivity principle by name
(e.g. "Morning peak — P1 deep work per Cal Newport morning primacy principle").

## Output Schema
Return a single JSON object with EXACTLY this structure:

{{
  "reasoning_summary": "<2-3 sentence overview of your approach for today>",
  "ordered_tasks": [
    {{
      "task_id": "<string — copy exactly from input>",
      "task_name": "<string — copy from content field>",
      "duration_minutes": <integer — session length, <= original duration>,
      "break_after_minutes": <integer — 0 unless specific break needed>,
      "can_be_split": <true | false>,
      "block_label": "<string — e.g. morning peak deep work>",
      "placement_reason": "<string — cite specific principle>",
      "scheduling_flags": ["<string>", ...]
    }}
  ],
  "pushed": [
    {{
      "task_id": "<string>",
      "task_name": "<string>",
      "reason": "<string>",
      "suggested_date": "<YYYY-MM-DD>"
    }}
  ],
  "flagged": [
    {{
      "task_id": "<string>",
      "task_name": "<string>",
      "issue": "<string>"
    }}
  ]
}}

Return ONLY the JSON object. No markdown. No backticks. No explanation outside the JSON."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


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
    messages = _build_schedule_prompt(
        enriched_tasks, free_windows, context, heuristics_summary, target_date
    )
    raw = _groq_json_call(client, SCHEDULE_MODEL, messages, "generate_schedule")

    if not isinstance(raw, dict):
        raise RuntimeError(f"generate_schedule expected a JSON object, got {type(raw)}")

    # Ensure all required keys exist
    for key in ("reasoning_summary", "ordered_tasks", "pushed", "flagged"):
        raw.setdefault(key, [] if key != "reasoning_summary" else "")

    return raw
