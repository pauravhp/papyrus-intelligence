"""Shared LLM scheduling pipeline helpers used by multiple commands."""

from src.models import TodoistTask


def build_enriched_task_details(
    tasks: list[TodoistTask],
    enriched_map: dict,
    priority_label_map: dict,
) -> list[dict]:
    """
    Merge LLM enrichment output with task detail fields for the generate_schedule call.

    For each task in `tasks`, look up its enrichment in `enriched_map` (keyed by task_id).
    If no enrichment exists, fall back to sensible defaults.
    Returns the list of merged dicts expected by generate_schedule's enriched_tasks argument.
    """
    result = []
    for t in tasks:
        base = enriched_map.get(
            t.id,
            {
                "task_id": t.id,
                "cognitive_load": "medium",
                "energy_requirement": "moderate",
                "suggested_block": "afternoon",
                "can_be_split": False,
                "scheduling_flags": ["never-schedule"] if "waiting" in t.labels else [],
            },
        )
        result.append(
            {
                **base,
                "content": t.content,
                "priority": priority_label_map.get(t.priority, "P4"),
                "duration_minutes": t.duration_minutes,
                "labels": t.labels,
                "deadline": t.deadline,
            }
        )
    return result
