from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    color_id: Optional[str]
    is_all_day: bool


@dataclass
class TodoistTask:
    id: str
    content: str
    project_id: str
    priority: int  # Todoist: 4=P1 (urgent), 3=P2, 2=P3, 1=P4 (normal)
    due_datetime: Optional[datetime]
    deadline: Optional[str]  # ISO date string e.g. "2026-04-10"
    duration_minutes: Optional[int]
    labels: list[str]
    is_inbox: bool


@dataclass
class FreeWindow:
    start: datetime
    end: datetime
    duration_minutes: int
    block_type: str  # "morning" | "afternoon" | "evening"


@dataclass
class ScheduledBlock:
    task_id: str
    task_name: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    work_block: str
    placement_reason: str = ""
    split_session: bool = False
    split_part: int = 0  # 0 = not split, 1 = first part, 2 = second part
