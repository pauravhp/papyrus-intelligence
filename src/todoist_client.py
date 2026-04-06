from datetime import datetime
from typing import Optional

import requests

from src.models import ScheduledBlock, TodoistTask

TODOIST_BASE = "https://api.todoist.com/api/v1"

# Duration is communicated via task labels, not Todoist's native duration field.
# The matched label is stripped from the labels list before the task reaches the LLM.
# Todoist stores labels WITHOUT the @ prefix in API responses.
# "@30min" in the UI → "30min" in the API. Keys here must match the raw stored value.
DURATION_LABEL_MAP: dict[str, int] = {
    "15min": 15,
    "30min": 30,
    "60min": 60,
    "90min": 90,
    "2h": 120,
    "3h": 180,
}


class TodoistClient:
    def __init__(self, api_token: str):
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._inbox_project_id: Optional[str] = None

    def _get_inbox_project_id(self) -> str:
        if self._inbox_project_id:
            return self._inbox_project_id

        resp = requests.get(f"{TODOIST_BASE}/projects", headers=self.headers)
        if resp.status_code == 401:
            raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
        resp.raise_for_status()

        data = resp.json()
        projects = data.get("results", data) if isinstance(data, dict) else data

        for proj in projects:
            if proj.get("inbox_project"):
                self._inbox_project_id = proj["id"]
                return self._inbox_project_id

        raise RuntimeError("Could not find Todoist inbox project")

    def _parse_task(self, item: dict, inbox_project_id: str) -> TodoistTask:
        due = item.get("due") or {}
        due_datetime: Optional[datetime] = None
        if due.get("datetime"):
            due_datetime = datetime.fromisoformat(due["datetime"].replace("Z", "+00:00"))
        elif due.get("date"):
            due_datetime = datetime.fromisoformat(due["date"])

        deadline: Optional[str] = None
        dl = item.get("deadline")
        if dl:
            deadline = dl.get("date")

        # Duration comes from labels, not from Todoist's native duration field.
        # Strip the matched duration label so it doesn't appear as a scheduling tag.
        raw_labels: list[str] = list(item.get("labels", []))
        duration_minutes: Optional[int] = None
        clean_labels: list[str] = []
        for label in raw_labels:
            if label in DURATION_LABEL_MAP:
                duration_minutes = DURATION_LABEL_MAP[label]
            else:
                clean_labels.append(label)

        return TodoistTask(
            id=item["id"],
            content=item["content"],
            project_id=item.get("project_id", ""),
            priority=item.get("priority", 1),
            due_datetime=due_datetime,
            deadline=deadline,
            duration_minutes=duration_minutes,
            labels=clean_labels,
            is_inbox=item.get("project_id") == inbox_project_id,
        )

    def _get_all_pages(self, url: str, params: dict) -> list[dict]:
        """Fetch all pages from a paginated v1 endpoint."""
        items: list[dict] = []
        cursor = None
        while True:
            if cursor:
                params = {**params, "cursor": cursor}
            resp = requests.get(url, headers=self.headers, params=params)
            if resp.status_code == 401:
                raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
            resp.raise_for_status()

            data = resp.json()
            page = data.get("results", data) if isinstance(data, dict) else data
            if isinstance(page, list):
                items.extend(page)
            else:
                break

            cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not cursor:
                break

        return items

    def get_tasks(self, filter_str: str = "today") -> list[TodoistTask]:
        inbox_id = self._get_inbox_project_id()
        raw = self._get_all_pages(
            f"{TODOIST_BASE}/tasks",
            {"filter": filter_str},
        )
        return [self._parse_task(item, inbox_id) for item in raw]

    def update_task_priority(self, task_id: str, priority: int) -> None:
        """
        Update a task's priority.  priority integer: 4=P1, 3=P2, 2=P3, 1=P4.
        Uses POST /api/v1/tasks/{task_id} — PATCH returns 405 in the v1 API.
        """
        resp = requests.post(
            f"{TODOIST_BASE}/tasks/{task_id}",
            headers=self.headers,
            json={"priority": priority},
        )
        if resp.status_code == 401:
            raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
        resp.raise_for_status()

    def add_comment(self, task_id: str, content: str) -> None:
        """Post a comment on a task via REST API v1."""
        resp = requests.post(
            f"{TODOIST_BASE}/comments",
            headers=self.headers,
            json={"task_id": task_id, "content": content},
        )
        if resp.status_code == 401:
            raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
        resp.raise_for_status()

    def get_inbox_tasks(self) -> list[TodoistTask]:
        inbox_id = self._get_inbox_project_id()
        raw = self._get_all_pages(
            f"{TODOIST_BASE}/tasks",
            {"project_id": inbox_id},
        )
        return [self._parse_task(item, inbox_id) for item in raw]


_WRITEBACK_TIMEZONE_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def write_schedule_to_todoist(
    scheduled_blocks: list[ScheduledBlock],
    pushed_tasks: list[dict],
    task_map: dict,
    context: dict,
    api_token: str,
) -> int:
    """
    Write confirmed schedule back to Todoist via individual REST API v1 calls.

    NOTE: Todoist Sync API v9 (sync/v9/sync) returns 410 Gone — it has been
    deprecated alongside REST v2. We fall back to individual POST calls per task
    against the REST v1 base URL.

    - Scheduled blocks: set due_datetime + duration + duration_unit on the task.
    - Split sessions (split_part == 1): write first session; add comment with both times.
    - Split sessions (split_part == 2): skip (covered by comment on part 1).
    - Pushed tasks with an existing due date: clear due_datetime (set to null).

    Returns the number of tasks successfully updated.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    # ── Build index of split part 2 blocks keyed by task_id ──────────────────
    split_part2: dict[str, ScheduledBlock] = {
        b.task_id: b for b in scheduled_blocks if b.split_part == 2
    }

    client = TodoistClient(api_token)
    split_comment_tasks: list[ScheduledBlock] = []
    n_updated = 0

    # ── Scheduled blocks ─────────────────────────────────────────────────────
    for block in scheduled_blocks:
        if block.split_part == 2:
            continue  # part 2 time is documented via comment on part 1

        # Format as ISO 8601 with timezone offset (e.g. 2026-04-05T13:00:00-07:00)
        due_str = block.start_time.isoformat()

        try:
            resp = requests.post(
                f"{TODOIST_BASE}/tasks/{block.task_id}",
                headers=headers,
                json={
                    "due_datetime": due_str,
                    "duration": block.duration_minutes,
                    "duration_unit": "minute",
                },
            )
            if resp.status_code == 401:
                raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
            resp.raise_for_status()
            n_updated += 1
        except Exception as exc:
            print(f"[WARN] Could not update '{block.task_name}': {exc}")
            continue

        if block.split_session and block.split_part == 1:
            split_comment_tasks.append(block)

    # ── Pushed tasks — clear due date if they previously had one ─────────────
    for pushed in pushed_tasks:
        task_id = pushed.get("task_id", "")
        original = task_map.get(task_id)
        if not original or original.due_datetime is None:
            continue  # nothing to clear
        try:
            resp = requests.post(
                f"{TODOIST_BASE}/tasks/{task_id}",
                headers=headers,
                json={"due_datetime": None},
            )
            if resp.status_code == 401:
                raise RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")
            resp.raise_for_status()
        except Exception as exc:
            print(f"[WARN] Could not clear due date for '{pushed.get('task_name', task_id)}': {exc}")

    # ── Post split-session comments ───────────────────────────────────────────
    for part1 in split_comment_tasks:
        part2 = split_part2.get(part1.task_id)
        if part2:
            comment = (
                f"Split session scheduled: "
                f"Part 1 at {part1.start_time.strftime('%H:%M')} ({part1.duration_minutes}min), "
                f"Part 2 at {part2.start_time.strftime('%H:%M')} ({part2.duration_minutes}min)"
            )
        else:
            comment = (
                f"Split session scheduled: "
                f"Part 1 at {part1.start_time.strftime('%H:%M')} ({part1.duration_minutes}min)"
            )
        try:
            client.add_comment(part1.task_id, comment)
        except Exception as exc:
            print(f"[WARN] Could not post split comment for '{part1.task_name}': {exc}")

    return n_updated
