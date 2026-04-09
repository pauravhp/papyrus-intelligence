"""Prompt builder for Step 1 — task enrichment."""

import json

from src.models import TodoistTask

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}


def build_enrich_prompt(
    tasks: list[TodoistTask],
    context: dict,
    productivity_science: dict,
) -> list[dict]:
    label_vocab = context.get("label_vocabulary", {})

    task_list = []
    for t in tasks:
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
