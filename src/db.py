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
            task_id               TEXT NOT NULL,
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
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO task_history (
            task_id, task_name, project_id, estimated_duration_mins,
            actual_duration_mins, scheduled_at, completed_at, day_of_week,
            was_rescheduled, reschedule_count, was_late_night_prior, cognitive_load_label
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id, task_name, project_id, estimated_duration_mins,
            actual_duration_mins, scheduled_at, completed_at, day_of_week,
            int(was_rescheduled), reschedule_count, int(was_late_night_prior),
            cognitive_load_label,
        ),
    )
    conn.commit()
    conn.close()


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
