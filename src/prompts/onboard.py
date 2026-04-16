"""Prompt builder for --onboard Stage 1 — calendar pattern analysis."""

import json


def build_onboard_prompt(patterns: dict, existing_context: dict) -> list[dict]:
    system = (
        "You are an AI scheduling assistant helping a user configure their personal scheduling agent. "
        "Analyze calendar pattern data and propose scheduling configuration values. "
        "Respond ONLY with valid JSON. No markdown fences. No explanations outside the JSON."
    )

    # Send only the scheduling-relevant parts of existing context
    context_summary = {
        "user": existing_context.get("user", {}),
        "current_sleep_config": existing_context.get("sleep", {}),
        "existing_daily_block_names": [
            b["name"] for b in existing_context.get("daily_blocks", [])
        ],
    }

    user = f"""## Task: Propose Scheduling Configuration from Calendar Patterns

You are setting up an AI scheduling assistant for a user.
Analyze the detected calendar patterns below and propose configuration values.

---

## Detected Calendar Patterns ({patterns.get('scan_window_days', 14)}-day scan)
{json.dumps(patterns, indent=2)}

---

## Existing Configuration Reference
{json.dumps(context_summary, indent=2)}

---

## Output Format

Return this exact JSON structure (top level — three keys):

{{
  "proposed_config": {{
    "sleep": {{
      "default_wake_time": "<HH:MM or null>",
      "default_sleep_time": "<HH:MM or null>",
      "morning_buffer_minutes": <int or null>,
      "first_task_not_before": "<HH:MM or null>",
      "weekend_nothing_before": "<HH:MM or null>"
    }},
    "daily_blocks": [
      {{
        "name": "<string>",
        "start": "<HH:MM>",
        "end": "<HH:MM>",
        "days": "all",
        "movable": false,
        "buffer_before_minutes": 0,
        "buffer_after_minutes": 0
      }}
    ],
    "inferences": {{
      "wake_time_reasoning": "<one sentence>",
      "sleep_time_reasoning": "<one sentence>",
      "uncertain_fields": ["<field names that need user confirmation>"]
    }}
  }},
  "detected_categories": [
    {{
      "name": "<descriptive user-facing name, e.g. Meetings & calls>",
      "color_name": "<GCal color name — MUST be one of: Lavender, Sage, Grape, Flamingo, Banana, Tangerine, Peacock, Blueberry, Basil, Tomato, Avocado>",
      "event_samples": ["<title1>", "<title2>", "<title3>"],
      "buffer_before_minutes": <must be one of: 0, 5, 15, 30>,
      "buffer_after_minutes": <must be one of: 0, 5, 15, 30>
    }}
  ],
  "questions_for_stage_2": [
    {{
      "field": "<config field path e.g. sleep.default_wake_time>",
      "question": "<clear, specific question for the user>",
      "current_inference": "<your best guess value>",
      "confidence": "high | medium | low"
    }}
  ]
}}

Rules:
- Use null for any sleep field you cannot confidently infer from the data
- detected_categories: for each color group in color_semantics, produce one entry
  - name: infer from event titles what these events mean to the user
  - color_name: use the color name key from color_semantics (already translated for you)
  - event_samples: up to 3 representative event titles from top_names
  - buffer_before_minutes / buffer_after_minutes: choose from 0, 5, 15, 30
    - meetings/calls: 15 before, 15 after
    - personal events: 30 before, 30 after
    - focus blocks: 0 before, 5 after
- If color_semantics is empty, return empty detected_categories array
- daily_blocks: ONLY include blocks you detected as truly recurring (3+ occurrences); skip meals unless explicitly on calendar
- questions_for_stage_2: generate 3-6 questions ONLY for medium/low confidence fields
- Do NOT ask about fields you can infer with high confidence from the data
- Wake time heuristic: earliest consistent events minus 60-90min ≈ wake time
- Sleep time heuristic: if events end after 10pm regularly, sleep is likely 12am-2am
- Weekend heuristic: if no weekend events before noon, infer weekend_nothing_before = "12:00" or "13:00"

Return ONLY the JSON object. No markdown. No backticks. No explanation text."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
