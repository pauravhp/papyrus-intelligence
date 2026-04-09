"""Read operations for the task_history table."""

import sqlite3
from datetime import datetime

from src.db import get_connection


def get_task_history_row(task_id: str) -> dict | None:
    """Return the most recent task_history row for a task_id, or None."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    )
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_todays_task_history(date_str: str) -> list[dict]:
    """
    Return unreviewed task_history rows for date_str
    (no completed_at, no actual_duration_mins).
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE substr(scheduled_at, 1, 10) = ?
          AND actual_duration_mins IS NULL
          AND completed_at IS NULL
        ORDER BY scheduled_at
        """,
        (date_str,),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_task_history_for_date(date_str: str) -> list[dict]:
    """
    Return task_history rows scheduled on date_str where completed_at IS NULL.
    Used by --unplan (wider filter than get_todays_task_history).
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE DATE(scheduled_at) = ?
          AND completed_at IS NULL
        ORDER BY scheduled_at
        """,
        (date_str,),
    )
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def get_task_history_for_replan(
    date_str: str, replan_from_iso: str
) -> tuple[list[dict], list[dict]]:
    """
    Split task_history for date_str into:
    - already_done: completed_at IS NOT NULL OR scheduled_at < replan_from_iso
    - to_replan:    scheduled_at >= replan_from_iso AND completed_at IS NULL
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT * FROM task_history WHERE DATE(scheduled_at) = ? ORDER BY scheduled_at",
        (date_str,),
    )
    all_rows = [dict(row) for row in c.fetchall()]
    conn.close()

    try:
        replan_dt = datetime.fromisoformat(replan_from_iso)
    except ValueError:
        replan_dt = None

    already_done: list[dict] = []
    to_replan: list[dict] = []

    for row in all_rows:
        done = row.get("completed_at") is not None
        if not done and replan_dt and row.get("scheduled_at"):
            try:
                sched_dt = datetime.fromisoformat(row["scheduled_at"])
                if sched_dt.tzinfo is not None and replan_dt.tzinfo is not None:
                    done = sched_dt < replan_dt
                else:
                    done = sched_dt.replace(tzinfo=None) < replan_dt.replace(tzinfo=None)
            except ValueError:
                pass
        if done:
            already_done.append(row)
        else:
            to_replan.append(row)

    return already_done, to_replan


def get_reschedule_count(task_id: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(MAX(reschedule_count), 0) FROM task_history WHERE task_id = ?",
        (task_id,),
    )
    result = c.fetchone()[0]
    conn.close()
    return result
