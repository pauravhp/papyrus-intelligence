"""
Lazy reconcile of confirmed schedules against external state (GCal + Todoist).

Public entry: reconcile_today(user_ctx, target_date) -> ReconcileDelta.

Spec: docs/superpowers/specs/2026-04-29-bidirectional-reconcile-design.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TaskMove:
    task_id: str
    old_start: str
    new_start: str
    old_end: str
    new_end: str


@dataclass
class TaskEdit:
    task_id: str
    field: Literal["title", "duration"]
    old_value: str | int
    new_value: str | int


@dataclass
class DropReason:
    task_id: str
    reason: Literal["todoist_deleted", "todoist_due_cleared"]
    gcal_state: Literal["present", "moved", "edited", "missing"]


@dataclass
class ReconcileDelta:
    moved: list[TaskMove] = field(default_factory=list)
    edited: list[TaskEdit] = field(default_factory=list)
    gcal_deleted: list[str] = field(default_factory=list)
    dropped: list[DropReason] = field(default_factory=list)
    skipped_reviewed: bool = False

    def has_writes(self) -> bool:
        return bool(self.moved or self.edited or self.gcal_deleted or self.dropped)


from datetime import datetime


@dataclass
class GcalState:
    kind: Literal["present", "moved", "edited", "missing"]
    title_changed: bool = False
    duration_changed: bool = False
    new_start: str | None = None  # populated if kind == "moved"
    new_end: str | None = None
    new_title: str | None = None  # populated if title_changed
    new_duration_minutes: int | None = None  # populated if duration_changed


def _to_utc_instant(iso: str) -> datetime:
    """Parse an ISO timestamp to a UTC-naive datetime for comparison."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz=None).replace(tzinfo=None)


def _duration_minutes_from(start_iso: str, end_iso: str) -> int:
    diff = _to_utc_instant(end_iso) - _to_utc_instant(start_iso)
    return int(diff.total_seconds() // 60)


def classify_gcal(gcal_by_id: dict, event_id: str, item: dict) -> GcalState:
    """Classify the GCal-side state of a scheduled item against the live GCal index."""
    if not event_id or event_id not in gcal_by_id:
        return GcalState(kind="missing")

    event = gcal_by_id[event_id]
    item_start = _to_utc_instant(item["start_time"])
    item_end = _to_utc_instant(item["end_time"])
    evt_start = _to_utc_instant(event["start_time"])
    evt_end = _to_utc_instant(event["end_time"])

    moved = item_start != evt_start
    title_changed = (item.get("task_name") or "") != (event.get("summary") or "")
    new_dur = _duration_minutes_from(event["start_time"], event["end_time"])
    duration_changed = new_dur != int(item.get("duration_minutes") or 0)

    if not moved and not title_changed and not duration_changed:
        return GcalState(kind="present")

    if moved:
        return GcalState(
            kind="moved",
            title_changed=title_changed,
            duration_changed=duration_changed,
            new_start=event["start_time"],
            new_end=event["end_time"],
            new_title=event.get("summary") if title_changed else None,
            new_duration_minutes=new_dur if duration_changed else None,
        )

    return GcalState(
        kind="edited",
        title_changed=title_changed,
        duration_changed=duration_changed,
        new_title=event.get("summary") if title_changed else None,
        new_duration_minutes=new_dur if duration_changed else None,
    )


from enum import Enum


class TodoistState(Enum):
    NA = "na"               # task_id starts with proj_ — no Todoist mirror
    PENDING = "pending"     # in active_ids
    COMPLETED = "completed" # in completed_ids
    DELETED = "deleted"     # in neither (collapses with due_cleared in v1)


def classify_todoist(active_ids: set[str], completed_ids: set[str], item: dict) -> TodoistState:
    """Classify the Todoist-side state of a scheduled item."""
    task_id = item.get("task_id") or ""
    if task_id.startswith("proj_"):
        return TodoistState.NA
    if task_id in completed_ids:
        return TodoistState.COMPLETED
    if task_id in active_ids:
        return TodoistState.PENDING
    return TodoistState.DELETED


from typing import Literal as _Literal

ApplyAction = _Literal["KEEP", "DROP"]


def _apply_rule(
    item: dict,
    gcal_state: GcalState,
    todoist_state: TodoistState,
    delta: ReconcileDelta,
) -> ApplyAction:
    """
    Apply the rule matrix from the spec (§6.3) to a single scheduled item.
    Mutates `item` in place when keeping; appends to `delta`. Returns "DROP"
    when the caller should remove the item from proposed_json.scheduled[].
    """
    # Todoist DELETED column always drops (regardless of GCal state) — except NA.
    if todoist_state == TodoistState.DELETED:
        delta.dropped.append(
            DropReason(
                task_id=item["task_id"],
                reason="todoist_deleted",
                gcal_state=gcal_state.kind,
            )
        )
        return "DROP"

    # GCal column rules apply for PENDING, COMPLETED, NA.
    if gcal_state.kind == "missing":
        item["gcal_deleted"] = True
        delta.gcal_deleted.append(item["task_id"])
        return "KEEP"

    if gcal_state.kind == "moved":
        delta.moved.append(
            TaskMove(
                task_id=item["task_id"],
                old_start=item["start_time"],
                new_start=gcal_state.new_start,
                old_end=item["end_time"],
                new_end=gcal_state.new_end,
            )
        )
        item["start_time"] = gcal_state.new_start
        item["end_time"] = gcal_state.new_end

    # MOVED can co-occur with title/duration edits — apply those too.
    if gcal_state.title_changed:
        delta.edited.append(
            TaskEdit(
                task_id=item["task_id"],
                field="title",
                old_value=item.get("task_name") or "",
                new_value=gcal_state.new_title or "",
            )
        )
        item["task_name"] = gcal_state.new_title

    if gcal_state.duration_changed:
        delta.edited.append(
            TaskEdit(
                task_id=item["task_id"],
                field="duration",
                old_value=int(item.get("duration_minutes") or 0),
                new_value=int(gcal_state.new_duration_minutes or 0),
            )
        )
        item["duration_minutes"] = int(gcal_state.new_duration_minutes or 0)

    return "KEEP"
