import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "schedule.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def setup_database() -> None:
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id               TEXT UNIQUE NOT NULL,
            task_name             TEXT,
            project_id            TEXT,
            estimated_duration_mins INTEGER,
            actual_duration_mins  INTEGER,
            scheduled_at          TEXT,
            completed_at          TEXT,
            day_of_week           TEXT,
            was_rescheduled       INTEGER DEFAULT 0,
            reschedule_count      INTEGER DEFAULT 0,
            was_late_night_prior  INTEGER DEFAULT 0,
            cognitive_load_label  TEXT,
            created_at            TEXT DEFAULT (datetime('now'))
        )
    """)

    # Safe migration: deduplicate any pre-existing rows before adding the unique
    # index, so this is safe to run against old databases with duplicate task_ids.
    # Keep only the most recent row per task_id (highest id).
    c.execute("""
        DELETE FROM task_history
        WHERE id NOT IN (
            SELECT MAX(id) FROM task_history GROUP BY task_id
        )
    """)

    # CREATE UNIQUE INDEX IF NOT EXISTS is a no-op if the index already exists.
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_history_task_id
        ON task_history(task_id)
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at        TEXT NOT NULL,
            schedule_date TEXT NOT NULL,
            proposed_json TEXT,
            confirmed     INTEGER DEFAULT 0,
            confirmed_at  TEXT,
            diff_json     TEXT
        )
    """)

    conn.commit()
    conn.close()


def insert_task_history(
    task_id: str,
    task_name: str,
    project_id: str,
    estimated_duration_mins: int,
    actual_duration_mins: int | None = None,
    scheduled_at: str | None = None,
    completed_at: str | None = None,
    day_of_week: str | None = None,
    was_rescheduled: bool = False,
    reschedule_count: int = 0,
    was_late_night_prior: bool = False,
    cognitive_load_label: str | None = None,
) -> None:
    """
    Upsert a scheduled task into task_history.

    Same slot (scheduled_at unchanged) → update in place, reschedule_count stays.
    Different slot → update scheduled_at, increment reschedule_count, set was_rescheduled=1.
    Never overwrites completed_at or actual_duration_mins (those are set by --review).
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO task_history (
            task_id, task_name, project_id, estimated_duration_mins,
            scheduled_at, day_of_week, was_late_night_prior, cognitive_load_label
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            scheduled_at            = excluded.scheduled_at,
            estimated_duration_mins = excluded.estimated_duration_mins,
            task_name               = excluded.task_name,
            cognitive_load_label    = excluded.cognitive_load_label,
            was_rescheduled = CASE
                WHEN task_history.scheduled_at IS NOT NULL
                 AND task_history.scheduled_at != excluded.scheduled_at
                THEN 1
                ELSE task_history.was_rescheduled
                END,
            reschedule_count = CASE
                WHEN task_history.scheduled_at IS NOT NULL
                 AND task_history.scheduled_at != excluded.scheduled_at
                THEN task_history.reschedule_count + 1
                ELSE task_history.reschedule_count
                END
        """,
        (
            task_id, task_name, project_id, estimated_duration_mins,
            scheduled_at, day_of_week,
            int(was_late_night_prior), cognitive_load_label,
        ),
    )
    conn.commit()
    conn.close()


def upsert_task_completed(
    task_id: str,
    task_name: str,
    project_id: str,
    estimated_duration_mins: int,
    actual_duration_mins: int | None,
    completed_at: str,
    scheduled_at: str | None = None,
    day_of_week: str | None = None,
) -> None:
    """
    Mark a task as completed. Inserts a row if none exists yet
    (e.g. completed without going through --plan-day), updates if it does.
    Does NOT overwrite actual_duration_mins if it was already set.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO task_history (
            task_id, task_name, project_id, estimated_duration_mins,
            actual_duration_mins, completed_at, scheduled_at, day_of_week
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            completed_at         = excluded.completed_at,
            actual_duration_mins = COALESCE(task_history.actual_duration_mins,
                                            excluded.actual_duration_mins),
            was_rescheduled      = 0
        """,
        (
            task_id, task_name, project_id, estimated_duration_mins,
            actual_duration_mins, completed_at, scheduled_at, day_of_week,
        ),
    )
    conn.commit()
    conn.close()


def mark_task_rescheduled_externally(task_id: str) -> None:
    """Mark a task as was_rescheduled=1 without changing any other fields.
    Called when --review detects that the user moved a task in Todoist directly."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE task_history SET was_rescheduled = 1 WHERE task_id = ?",
        (task_id,),
    )
    conn.commit()
    conn.close()


def mark_task_partial(
    task_id: str,
    date_str: str,
    actual_duration_mins: int,
) -> None:
    """Record how much was actually done; marks was_rescheduled=1."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE task_history
        SET actual_duration_mins = ?,
            was_rescheduled = 1
        WHERE task_id = ?
          AND substr(scheduled_at, 1, 10) = ?
          AND completed_at IS NULL
        """,
        (actual_duration_mins, task_id, date_str),
    )
    conn.commit()
    conn.close()


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
    Return all task_history rows for date_str that are not yet reviewed
    (no completed_at, no actual_duration_mins). Used for orphan detection.
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


def insert_schedule_log(
    schedule_date: str,
    proposed_json: dict | str,
    confirmed: bool = False,
    confirmed_at: str | None = None,
    diff_json: dict | str | None = None,
) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO schedule_log (run_at, schedule_date, proposed_json, confirmed, confirmed_at, diff_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            schedule_date,
            json.dumps(proposed_json) if not isinstance(proposed_json, str) else proposed_json,
            int(confirmed),
            confirmed_at,
            json.dumps(diff_json) if diff_json and not isinstance(diff_json, str) else diff_json,
        ),
    )
    conn.commit()
    conn.close()


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
