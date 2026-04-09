"""SQL helpers for --sync drift detection."""

import json
import sqlite3
from datetime import datetime

from src.db import get_connection


def get_task_history_for_sync(date_str: str) -> list[dict]:
    """
    Return agent-scheduled task_history rows for date_str that have a scheduled_at.
    Rows where was_agent_scheduled IS NULL are included (treated as agent-scheduled).
    Deduplicates by task_id, keeping the highest id row.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE DATE(scheduled_at) = ?
          AND scheduled_at IS NOT NULL
          AND COALESCE(was_agent_scheduled, 1) = 1
        ORDER BY id DESC
        """,
        (date_str,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    seen: dict[str, dict] = {}
    for row in rows:
        tid = row["task_id"]
        if tid not in seen:
            seen[tid] = row
    return list(seen.values())


def get_task_ids_for_date(date_str: str) -> set[str]:
    """
    Return all task_ids in task_history scheduled on date_str,
    regardless of was_agent_scheduled. Used by --sync to skip already-known tasks.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT task_id FROM task_history WHERE DATE(scheduled_at) = ?",
        (date_str,),
    )
    result = {row[0] for row in c.fetchall()}
    conn.close()
    return result


def sync_apply_case_a(task_id: str, date_str: str, new_scheduled_at: str) -> None:
    """Case A: task time moved same day — update scheduled_at, increment reschedule_count."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE task_history
        SET scheduled_at     = ?,
            sync_source      = 'manual',
            was_rescheduled  = 1,
            reschedule_count = reschedule_count + 1
        WHERE task_id = ?
          AND DATE(scheduled_at) = ?
        """,
        (new_scheduled_at, task_id, date_str),
    )
    conn.commit()
    conn.close()


def sync_apply_case_b(task_id: str, date_str: str) -> None:
    """Case B: task moved to different day or due cleared — mark was_agent_scheduled=0."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE task_history
        SET sync_source        = 'manual',
            was_agent_scheduled = 0
        WHERE task_id = ?
          AND DATE(scheduled_at) = ?
        """,
        (task_id, date_str),
    )
    conn.commit()
    conn.close()


def sync_apply_case_c(task_id: str, date_str: str, completed_at: str) -> None:
    """Case C: task completed or deleted outside --review — set completed_at."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE task_history
        SET completed_at = ?,
            sync_source  = 'sync'
        WHERE task_id = ?
          AND DATE(scheduled_at) = ?
          AND completed_at IS NULL
        """,
        (completed_at, task_id, date_str),
    )
    conn.commit()
    conn.close()


def sync_inject_task(
    task_id: str,
    task_name: str,
    project_id: str,
    estimated_duration_mins: int | None,
    scheduled_at: str,
) -> bool:
    """
    Insert a user-scheduled task (not via agent) into task_history.
    was_agent_scheduled=0 excludes it from quality score and model training.
    Returns True if a new row was inserted, False if it already existed.
    """
    day_of_week: str | None = None
    try:
        day_of_week = datetime.fromisoformat(scheduled_at).strftime("%A")
    except (ValueError, TypeError):
        pass

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO task_history (
            task_id, task_name, project_id, estimated_duration_mins,
            scheduled_at, day_of_week, sync_source, was_agent_scheduled
        ) VALUES (?, ?, ?, ?, ?, ?, 'user_injected', 0)
        ON CONFLICT(task_id) DO NOTHING
        """,
        (task_id, task_name, project_id, estimated_duration_mins,
         scheduled_at, day_of_week),
    )
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def get_user_injected_for_deletion_check(date_str: str) -> list[dict]:
    """
    Return user-injected task_history rows (was_agent_scheduled=0) for date_str
    where completed_at IS NULL. Used by --sync to detect deletions of user-scheduled
    tasks, which are excluded from the main agent-row sync loop.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE DATE(scheduled_at) = ?
          AND scheduled_at IS NOT NULL
          AND was_agent_scheduled = 0
          AND completed_at IS NULL
        """,
        (date_str,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def append_sync_diff(date_str: str, changes: list[dict]) -> None:
    """
    Append sync change records to the diff_json column of the most recent
    confirmed schedule_log row for date_str. Preserves existing diff_json content.
    """
    if not changes:
        return
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT id, diff_json FROM schedule_log
        WHERE schedule_date = ? AND confirmed = 1
        ORDER BY id DESC LIMIT 1
        """,
        (date_str,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return

    existing: dict = {}
    if row["diff_json"]:
        try:
            existing = json.loads(row["diff_json"])
            if not isinstance(existing, dict):
                existing = {"original": existing}
        except (json.JSONDecodeError, TypeError):
            existing = {}

    sync_entries: list = existing.get("sync_changes", [])
    sync_entries.append({"sync_at": datetime.now().isoformat(), "changes": changes})
    existing["sync_changes"] = sync_entries

    c.execute(
        "UPDATE schedule_log SET diff_json = ? WHERE id = ?",
        (json.dumps(existing), row["id"]),
    )
    conn.commit()
    conn.close()
