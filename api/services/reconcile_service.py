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
