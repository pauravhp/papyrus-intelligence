"""Write operations for the task_history table."""

from datetime import datetime

from src.db import get_connection


def _compute_time_bucket(
    scheduled_at: str,
    first_task_not_before: str = "10:30",
) -> tuple[str | None, str | None]:
    """
    Derive (time_of_day_bucket, window_type) from a scheduled_at ISO string.
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
    morning_start = fh * 60 + fm
    morning_end   = morning_start + 240
    trough_end    = morning_end + 120
    afternoon_end = 18 * 60
    evening_end   = 21 * 60

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
    was_deep_work: int = 0,
    back_to_back: int = 0,
    pre_meeting: int = 0,
    sync_source: str = "agent",
    was_agent_scheduled: int = 1,
    first_task_not_before: str = "10:30",
) -> None:
    """
    Upsert a scheduled task into task_history.

    Same slot → update in place, reschedule_count stays.
    Different slot → update scheduled_at, increment reschedule_count, set was_rescheduled=1.
    Never overwrites completed_at or actual_duration_mins (those are set by --review).
    session_number_today is set on first INSERT and never changed on upsert.
    """
    time_bucket, window_type_val = _compute_time_bucket(
        scheduled_at or "", first_task_not_before
    )

    conn = get_connection()
    c = conn.cursor()

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
    Mark a task as completed. Inserts if no row exists yet, updates if it does.
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
            actual_duration_mins, estimated_duration_mins,
            actual_duration_mins, estimated_duration_mins,
        ),
    )
    conn.commit()
    conn.close()


def mark_task_rescheduled_externally(task_id: str) -> None:
    """Mark was_rescheduled=1 without changing any other fields."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE task_history SET was_rescheduled = 1 WHERE task_id = ?",
        (task_id,),
    )
    conn.commit()
    conn.close()


def mark_task_partial(task_id: str, date_str: str, actual_duration_mins: int) -> None:
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
    """Delete ALL task_history rows for a task_id."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()


def set_incomplete_reason(task_id: str, reason: str | None) -> None:
    """Store the incomplete reason after --review."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE task_history SET incomplete_reason = ? WHERE task_id = ?",
        (reason, task_id),
    )
    conn.commit()
    conn.close()
