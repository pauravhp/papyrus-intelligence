import sqlite3
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

    # Safe migration: add replan_trigger column if it doesn't already exist
    try:
        c.execute("ALTER TABLE schedule_log ADD COLUMN replan_trigger TEXT")
    except Exception:
        pass  # column already exists

    # Safe migration: add quality_score to schedule_log
    try:
        c.execute("ALTER TABLE schedule_log ADD COLUMN quality_score REAL")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Safe migration: Phase-3 habit-learning columns on task_history.
    # Each ALTER TABLE is a no-op if the column already exists (caught by OperationalError).
    _NEW_TASK_HISTORY_COLS = [
        ("time_of_day_bucket", "TEXT"),
        ("window_type", "TEXT"),
        ("was_deep_work", "INTEGER"),
        ("session_number_today", "INTEGER"),
        ("back_to_back", "INTEGER"),
        ("pre_meeting", "INTEGER"),
        ("estimated_vs_actual_ratio", "REAL"),
        ("incomplete_reason", "TEXT"),
        ("sync_source", "TEXT"),
        ("was_agent_scheduled", "INTEGER"),
        ("mood_tag", "TEXT"),
    ]
    for col_name, col_type in _NEW_TASK_HISTORY_COLS:
        try:
            c.execute(
                f"ALTER TABLE task_history ADD COLUMN {col_name} {col_type}"
            )
        except sqlite3.OperationalError:
            pass  # column already exists

    c.execute("""
        CREATE TABLE IF NOT EXISTS project_budgets (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            todoist_task_id      TEXT UNIQUE NOT NULL,
            project_name         TEXT NOT NULL,
            total_budget_hours   REAL NOT NULL,
            remaining_hours      REAL NOT NULL,
            session_min_minutes  INTEGER NOT NULL DEFAULT 60,
            session_max_minutes  INTEGER NOT NULL DEFAULT 180,
            deadline             TEXT,
            priority             INTEGER NOT NULL DEFAULT 3,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
