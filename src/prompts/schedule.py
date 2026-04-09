"""Prompt builder for Step 2 — schedule generation."""

import json

from src.models import FreeWindow


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


def build_schedule_prompt(
    enriched_tasks: list[dict],
    free_windows: list[FreeWindow],
    context: dict,
    heuristics_summary: dict,
    target_date: str,
) -> list[dict]:
    rules_cfg = context.get("rules", {})
    hard_rules = rules_cfg.get("hard", context.get("rules_plaintext", []))
    soft_rules = rules_cfg.get("soft", [])

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

## Hard Rules — NEVER VIOLATE THESE (enforced in code)
{json.dumps(hard_rules, indent=2)}

---

## Soft Rules — Productivity Preferences (use judgment, not absolute)
{json.dumps(soft_rules, indent=2)}

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
