"""SQL query functions for the project_budgets table."""

import sqlite3
from datetime import datetime

from src.db import get_connection


def compute_deadline_pressure(deadline_str: str | None, remaining_hours: float) -> str:
    """
    Pure logic — no DB calls.
    Returns: 'critical' | 'at_risk' | 'comfortable' | 'no_deadline'
    """
    if not deadline_str:
        return "no_deadline"
    try:
        deadline_dt = datetime.fromisoformat(deadline_str)
    except ValueError:
        return "no_deadline"

    days_left = (deadline_dt.date() - datetime.now().date()).days
    days_needed = remaining_hours / 3.0 if remaining_hours > 0 else 0

    if days_left <= 0:
        return "critical"
    if days_needed >= days_left:
        return "critical"
    if days_needed >= days_left * 0.75:
        return "at_risk"
    return "comfortable"


def create_project_budget(
    todoist_task_id: str,
    project_name: str,
    total_budget_hours: float,
    session_min_minutes: int = 60,
    session_max_minutes: int = 180,
    deadline: str | None = None,
    priority: int = 3,
) -> None:
    now = datetime.now().isoformat()
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO project_budgets (
            todoist_task_id, project_name, total_budget_hours, remaining_hours,
            session_min_minutes, session_max_minutes, deadline, priority,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(todoist_task_id) DO UPDATE SET
            project_name        = excluded.project_name,
            total_budget_hours  = excluded.total_budget_hours,
            session_min_minutes = excluded.session_min_minutes,
            session_max_minutes = excluded.session_max_minutes,
            deadline            = excluded.deadline,
            priority            = excluded.priority,
            updated_at          = excluded.updated_at
        """,
        (
            todoist_task_id, project_name, total_budget_hours, total_budget_hours,
            session_min_minutes, session_max_minutes, deadline, priority,
            now, now,
        ),
    )
    conn.commit()
    conn.close()


def get_all_active_budgets() -> list[dict]:
    """Return all budget rows with remaining_hours > 0."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM project_budgets WHERE remaining_hours > 0 ORDER BY priority DESC, deadline"
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_budget_by_task_id(todoist_task_id: str) -> dict | None:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM project_budgets WHERE todoist_task_id = ?",
        (todoist_task_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def decrement_budget(todoist_task_id: str, hours_worked: float) -> float:
    """Subtract hours_worked from remaining_hours (floor 0). Returns new value."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE project_budgets
        SET remaining_hours = MAX(0, remaining_hours - ?),
            updated_at = ?
        WHERE todoist_task_id = ?
        """,
        (hours_worked, datetime.now().isoformat(), todoist_task_id),
    )
    conn.commit()
    c.execute(
        "SELECT remaining_hours FROM project_budgets WHERE todoist_task_id = ?",
        (todoist_task_id,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def add_to_budget(todoist_task_id: str, hours: float) -> float:
    """Add hours to remaining_hours (cap at total_budget_hours). Returns new value."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE project_budgets
        SET remaining_hours = MIN(total_budget_hours, remaining_hours + ?),
            updated_at = ?
        WHERE todoist_task_id = ?
        """,
        (hours, datetime.now().isoformat(), todoist_task_id),
    )
    conn.commit()
    c.execute(
        "SELECT remaining_hours FROM project_budgets WHERE todoist_task_id = ?",
        (todoist_task_id,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def update_budget_fields(
    todoist_task_id: str,
    session_min_minutes: int | None = None,
    session_max_minutes: int | None = None,
    deadline: str | None = None,
) -> None:
    """Patch individual budget fields without touching remaining_hours."""
    updates = []
    params: list = []
    if session_min_minutes is not None:
        updates.append("session_min_minutes = ?")
        params.append(session_min_minutes)
    if session_max_minutes is not None:
        updates.append("session_max_minutes = ?")
        params.append(session_max_minutes)
    if deadline is not None:
        updates.append("deadline = ?")
        params.append(deadline)
    if not updates:
        return
    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(todoist_task_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        f"UPDATE project_budgets SET {', '.join(updates)} WHERE todoist_task_id = ?",
        params,
    )
    conn.commit()
    conn.close()


def get_budget_by_name(name: str) -> list[dict]:
    """Return active budget rows whose project_name contains `name` (case-insensitive)."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM project_budgets WHERE LOWER(project_name) LIKE ? AND remaining_hours > 0",
        (f"%{name.lower()}%",),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def find_budget_by_name(name: str) -> list[dict]:
    """Case-insensitive search across ALL budget rows (including exhausted)."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM project_budgets WHERE LOWER(project_name) LIKE ?",
        (f"%{name.lower()}%",),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def reset_project_budget_hours(todoist_task_id: str) -> float:
    """Reset remaining_hours to total_budget_hours. Returns new value."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE project_budgets
        SET remaining_hours = total_budget_hours,
            updated_at = ?
        WHERE todoist_task_id = ?
        """,
        (datetime.now().isoformat(), todoist_task_id),
    )
    conn.commit()
    c.execute(
        "SELECT remaining_hours FROM project_budgets WHERE todoist_task_id = ?",
        (todoist_task_id,),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0.0


def delete_project_budget(todoist_task_id: str) -> None:
    """Remove a project budget entry from project_budgets."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM project_budgets WHERE todoist_task_id = ?",
        (todoist_task_id,),
    )
    conn.commit()
    conn.close()
