from datetime import datetime
from typing import Optional

import requests

from src.models import TodoistTask

TODOIST_BASE = "https://api.todoist.com/api/v1"


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

        duration_minutes: Optional[int] = None
        dur = item.get("duration")
        if dur and dur.get("unit") == "minute":
            amount = dur.get("amount", 0)
            duration_minutes = int(amount) if amount else None

        deadline: Optional[str] = None
        dl = item.get("deadline")
        if dl:
            deadline = dl.get("date")

        return TodoistTask(
            id=item["id"],
            content=item["content"],
            project_id=item.get("project_id", ""),
            priority=item.get("priority", 1),
            due_datetime=due_datetime,
            deadline=deadline,
            duration_minutes=duration_minutes,
            labels=item.get("labels", []),
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

    def get_inbox_tasks(self) -> list[TodoistTask]:
        inbox_id = self._get_inbox_project_id()
        raw = self._get_all_pages(
            f"{TODOIST_BASE}/tasks",
            {"project_id": inbox_id},
        )
        return [self._parse_task(item, inbox_id) for item in raw]
