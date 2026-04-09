import json
import sqlite3
from datetime import datetime, timedelta
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


# ── Time-bucket helpers ────────────────────────────────────────────────────────


def _compute_time_bucket(
    scheduled_at: str,
    first_task_not_before: str = "10:30",
) -> tuple[str | None, str | None]:
    """
    Derive (time_of_day_bucket, window_type) from a scheduled_at ISO string.

    Boundaries are anchored to first_task_not_before (proxy for wake+buffer):
      morning_peak:  [first_task, first_task+4h)  → window_type 'peak'
      trough:        [+4h, +6h)                    → window_type 'trough'
      afternoon_peak:[+6h, 18:00)                  → window_type 'secondary'
      evening:       [18:00, 21:00)                → window_type 'other'
      late_night:    [21:00, ...) and before start → window_type 'other'

    Returns (None, None) if scheduled_at is empty or unparseable.
    """
    if not scheduled_at:
        return None, None
    try:
        dt = datetime.fromisoformat(scheduled_at)
    except (ValueError, TypeError):
        return None, None

    fh, fm = map(int, first_task_not_before.split(":"))
    t_mins = dt.hour * 60 + dt.minute
    morning_start = fh * 60 + fm          # e.g. 10*60+30 = 630
    morning_end   = morning_start + 240   # +4h → 870  (14:30)
    trough_end    = morning_end + 120     # +2h → 990  (16:30)
    afternoon_end = 18 * 60               #          1080 (18:00)
    evening_end   = 21 * 60              #          1260 (21:00)

    if t_mins < morning_start:
        return "late_night", "other"
    elif t_mins < morning_end:
        return "morning_peak", "peak"
    elif t_mins < trough_end:
        return "trough", "trough"
    elif t_mins < afternoon_end:
        return "afternoon_peak", "secondary"
    elif t_mins < evening_end:
        return "evening", "other"
    else:
        return "late_night", "other"


# ── project_budgets helpers ────────────────────────────────────────────────────


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
    """
    Subtract hours_worked from remaining_hours (floor at 0).
    Returns the new remaining_hours value.
    """
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
    """
    Add hours to remaining_hours (never exceeds total_budget_hours).
    Returns the new remaining_hours value.
    """
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
    # Assume ~3 working hours of budget work per day as baseline
    days_needed = remaining_hours / 3.0 if remaining_hours > 0 else 0

    if days_left <= 0:
        return "critical"
    if days_needed >= days_left:
        return "critical"
    if days_needed >= days_left * 0.75:
        return "at_risk"
    return "comfortable"


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
    # Phase-3 habit-learning fields — all nullable; existing callers get safe defaults
    was_deep_work: int = 0,
    back_to_back: int = 0,
    pre_meeting: int = 0,
    sync_source: str = "agent",
    was_agent_scheduled: int = 1,
    first_task_not_before: str = "10:30",
) -> None:
    """
    Upsert a scheduled task into task_history.

    Same slot (scheduled_at unchanged) → update in place, reschedule_count stays.
    Different slot → update scheduled_at, increment reschedule_count, set was_rescheduled=1.
    Never overwrites completed_at or actual_duration_mins (those are set by --review).
    session_number_today is set on first INSERT and never changed on upsert.
    """
    time_bucket, window_type_val = _compute_time_bucket(
        scheduled_at or "", first_task_not_before
    )

    conn = get_connection()
    c = conn.cursor()

    # session_number_today: count already-inserted rows for this date, then +1.
    # Computed inside the transaction so it's consistent with concurrent inserts.
    session_number_today: int | None = None
    if scheduled_at:
        c.execute(
            "SELECT COUNT(*) FROM task_history WHERE DATE(scheduled_at) = DATE(?)",
            (scheduled_at,),
        )
        session_number_today = c.fetchone()[0] + 1

    c.execute(
        """
        INSERT INTO task_history (
            task_id, task_name, project_id, estimated_duration_mins,
            scheduled_at, day_of_week, was_late_night_prior, cognitive_load_label,
            time_of_day_bucket, window_type, was_deep_work, session_number_today,
            back_to_back, pre_meeting, sync_source, was_agent_scheduled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            scheduled_at            = excluded.scheduled_at,
            estimated_duration_mins = excluded.estimated_duration_mins,
            task_name               = excluded.task_name,
            cognitive_load_label    = excluded.cognitive_load_label,
            time_of_day_bucket      = excluded.time_of_day_bucket,
            window_type             = excluded.window_type,
            was_deep_work           = excluded.was_deep_work,
            back_to_back            = excluded.back_to_back,
            pre_meeting             = excluded.pre_meeting,
            sync_source             = excluded.sync_source,
            was_agent_scheduled     = excluded.was_agent_scheduled,
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
            time_bucket, window_type_val, int(was_deep_work), session_number_today,
            int(back_to_back), int(pre_meeting), sync_source, int(was_agent_scheduled),
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
            actual_duration_mins, completed_at, scheduled_at, day_of_week,
            estimated_vs_actual_ratio
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            CASE WHEN ? IS NOT NULL AND ? > 0
                 THEN CAST(? AS REAL) / ?
                 ELSE NULL END
        )
        ON CONFLICT(task_id) DO UPDATE SET
            completed_at         = excluded.completed_at,
            actual_duration_mins = COALESCE(task_history.actual_duration_mins,
                                            excluded.actual_duration_mins),
            was_rescheduled      = 0,
            estimated_vs_actual_ratio = CASE
                WHEN excluded.actual_duration_mins IS NOT NULL
                     AND task_history.estimated_duration_mins > 0
                THEN CAST(excluded.actual_duration_mins AS REAL)
                     / task_history.estimated_duration_mins
                ELSE task_history.estimated_vs_actual_ratio
                END
        """,
        (
            task_id, task_name, project_id, estimated_duration_mins,
            actual_duration_mins, completed_at, scheduled_at, day_of_week,
            # ratio params: actual IS NOT NULL check, estimated > 0 check, actual, estimated
            actual_duration_mins, estimated_duration_mins,
            actual_duration_mins, estimated_duration_mins,
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
            was_rescheduled = 1,
            estimated_vs_actual_ratio = CASE
                WHEN ? IS NOT NULL AND estimated_duration_mins > 0
                THEN CAST(? AS REAL) / estimated_duration_mins
                ELSE estimated_vs_actual_ratio
                END
        WHERE task_id = ?
          AND substr(scheduled_at, 1, 10) = ?
          AND completed_at IS NULL
        """,
        (actual_duration_mins, actual_duration_mins, actual_duration_mins,
         task_id, date_str),
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
    replan_trigger: str | None = None,
) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO schedule_log (run_at, schedule_date, proposed_json, confirmed, confirmed_at, diff_json, replan_trigger)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            schedule_date,
            json.dumps(proposed_json) if not isinstance(proposed_json, str) else proposed_json,
            int(confirmed),
            confirmed_at,
            json.dumps(diff_json) if diff_json and not isinstance(diff_json, str) else diff_json,
            replan_trigger,
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


# ── unplan / delete / reset helpers ───────────────────────────────────────────


def get_task_history_for_date(date_str: str) -> list[dict]:
    """
    Return all task_history rows scheduled on date_str where completed_at IS NULL.
    Used by --unplan (wider than get_todays_task_history which also filters actual_duration_mins).
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
    Split task_history for date_str into two groups:
    - already_done: completed_at IS NOT NULL OR scheduled_at < replan_from_iso
                    (in-progress or finished — never touch)
    - to_replan:    scheduled_at >= replan_from_iso AND completed_at IS NULL
                    (will be rescheduled)

    replan_from_iso is an ISO 8601 datetime string.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE DATE(scheduled_at) = ?
        ORDER BY scheduled_at
        """,
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
                # Normalise to naive for comparison if tz awareness differs
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


def delete_task_history_row(task_id: str, date_str: str) -> None:
    """Delete a single task_history row by task_id + scheduled date."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM task_history WHERE task_id = ? AND DATE(scheduled_at) = ?",
        (task_id, date_str),
    )
    conn.commit()
    conn.close()


def delete_task_history_all(task_id: str) -> None:
    """Delete ALL task_history rows for a task_id (used by --delete-project / --reset-project)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()


def delete_schedule_log_for_date(date_str: str) -> None:
    """Delete schedule_log rows for a given date (used by full-day --unplan)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM schedule_log WHERE DATE(schedule_date) = ?",
        (date_str,),
    )
    conn.commit()
    conn.close()


def reset_project_budget_hours(todoist_task_id: str) -> float:
    """
    Reset remaining_hours to total_budget_hours.
    Returns the new remaining_hours value.
    """
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


def find_budget_by_name(name: str) -> list[dict]:
    """
    Case-insensitive substring search across ALL project_budgets rows
    (including exhausted ones — remaining_hours may be 0).
    """
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


# ── Phase-3 review helpers ─────────────────────────────────────────────────────


def set_incomplete_reason(task_id: str, reason: str | None) -> None:
    """
    Store the incomplete reason for a task after --review.
    reason: 'time' | 'motivation' | 'blocked' | 'skipped' | None
    NULL is stored when the user skips the prompt (empty input or Ctrl+C).
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE task_history SET incomplete_reason = ? WHERE task_id = ?",
        (reason, task_id),
    )
    conn.commit()
    conn.close()


def compute_quality_score(date_str: str) -> float:
    """
    Compute a 0–100 quality score for the schedule on date_str.

    Base score: (completed_count / scheduled_count) * 100

    Deductions (applied after base, floor 0):
      -5 per same-day rescheduled task (reschedule_count > 0, scheduled and
         created on the same date — indicates --add-task disruption)
      -3 per back-to-back incomplete pair (both tasks back_to_back=1,
         incomplete — signals over-packing)
      -2 per deep-work task completed in trough window (lucky placement)

    Returns 0.0 if no agent-scheduled tasks exist for the date.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM task_history
        WHERE DATE(scheduled_at) = ?
          AND COALESCE(was_agent_scheduled, 1) = 1
        """,
        (date_str,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return 0.0

    scheduled_count = len(rows)
    completed_count = sum(1 for r in rows if r.get("completed_at") is not None)

    base = (completed_count / scheduled_count) * 100.0

    # Deduction 1: same-day reschedules (--add-task disruption)
    same_day_rescheduled = sum(
        1 for r in rows
        if (r.get("reschedule_count") or 0) > 0
        and (r.get("was_agent_scheduled") or 1) == 1
        and r.get("scheduled_at") and r.get("created_at")
        and r["scheduled_at"][:10] == r["created_at"][:10]
    )
    deduct_reschedule = same_day_rescheduled * 5

    # Deduction 2: back-to-back incomplete pairs
    b2b_incomplete = sum(
        1 for r in rows
        if r.get("back_to_back") == 1 and r.get("completed_at") is None
    )
    deduct_b2b = (b2b_incomplete // 2) * 3

    # Deduction 3: deep-work completed in trough (bad placement that got lucky)
    dw_trough_completed = sum(
        1 for r in rows
        if r.get("was_deep_work") == 1
        and r.get("window_type") == "trough"
        and r.get("completed_at") is not None
    )
    deduct_dw_trough = dw_trough_completed * 2

    score = max(0.0, base - deduct_reschedule - deduct_b2b - deduct_dw_trough)
    return round(score, 1)


def update_quality_score(schedule_date: str, score: float) -> None:
    """
    Write quality_score to the most recent confirmed schedule_log row for
    schedule_date. Uses a subquery to avoid SQLite's lack of ORDER BY in UPDATE.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE schedule_log
        SET quality_score = ?
        WHERE id = (
            SELECT id FROM schedule_log
            WHERE schedule_date = ? AND confirmed = 1
            ORDER BY id DESC LIMIT 1
        )
        """,
        (score, schedule_date),
    )
    conn.commit()
    conn.close()


# ── --sync drift detection helpers ────────────────────────────────────────────


def get_task_history_for_sync(date_str: str) -> list[dict]:
    """
    Return agent-scheduled task_history rows for date_str that have a scheduled_at.
    Includes rows where was_agent_scheduled IS NULL (pre-schema rows).
    Deduplicates by task_id, keeping the highest id row (UNIQUE constraint should
    prevent dups post-migration, but this handles dirty DBs defensively).
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

    # Deduplicate by task_id, keeping highest id
    seen: dict[str, dict] = {}
    for row in rows:
        tid = row["task_id"]
        if tid not in seen:
            seen[tid] = row
    return list(seen.values())


def get_task_ids_for_date(date_str: str) -> set[str]:
    """
    Return all task_ids in task_history that have scheduled_at on date_str,
    regardless of was_agent_scheduled. Used by --sync to detect user-injected tasks
    that are already known.
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
    """
    Case A: task time moved to a different time on the same day.
    Update scheduled_at, mark as manual, increment reschedule_count.
    """
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
    """
    Case B: task moved to a different day (or due date cleared).
    Mark was_agent_scheduled=0 so the row is excluded from training and from
    quality score, but preserved as a historical record.
    """
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
    """
    Case C: task completed (or deleted) outside --review.
    Set completed_at; leave actual_duration_mins NULL to distinguish from a
    --review completion (which always sets actual_duration_mins).
    """
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
) -> None:
    """
    Insert a user-scheduled task (not via agent) into task_history.
    was_agent_scheduled=0 excludes it from quality score and model training.
    ON CONFLICT DO NOTHING: if somehow already present, leave it unchanged.
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
    conn.commit()
    conn.close()


def append_sync_diff(date_str: str, changes: list[dict]) -> None:
    """
    Append sync change records to the diff_json column of the most recent
    confirmed schedule_log row for date_str.

    diff_json is extended with a "sync_changes" list; existing content is preserved.
    If no confirmed schedule_log row exists, this is a no-op.
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
    sync_entries.append({
        "sync_at": datetime.now().isoformat(),
        "changes": changes,
    })
    existing["sync_changes"] = sync_entries

    c.execute(
        "UPDATE schedule_log SET diff_json = ? WHERE id = ?",
        (json.dumps(existing), row["id"]),
    )
    conn.commit()
    conn.close()
