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
