"""SQL query functions for the schedule_log table and quality scoring."""

import json
import sqlite3
from datetime import datetime

from src.db import get_connection


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


def compute_quality_score(date_str: str) -> float:
    """
    Compute a 0–100 quality score for the schedule on date_str.

    Base score: (completed_count / scheduled_count) * 100

    Deductions:
      -5 per same-day rescheduled task (--add-task disruption)
      -3 per back-to-back incomplete pair (over-packing signal)
      -2 per deep-work task completed in trough (lucky placement)

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

    same_day_rescheduled = sum(
        1 for r in rows
        if (r.get("reschedule_count") or 0) > 0
        and (r.get("was_agent_scheduled") or 1) == 1
        and r.get("scheduled_at") and r.get("created_at")
        and r["scheduled_at"][:10] == r["created_at"][:10]
    )
    b2b_incomplete = sum(
        1 for r in rows
        if r.get("back_to_back") == 1 and r.get("completed_at") is None
    )
    dw_trough_completed = sum(
        1 for r in rows
        if r.get("was_deep_work") == 1
        and r.get("window_type") == "trough"
        and r.get("completed_at") is not None
    )

    score = max(
        0.0,
        base - same_day_rescheduled * 5 - (b2b_incomplete // 2) * 3 - dw_trough_completed * 2,
    )
    return round(score, 1)


def update_quality_score(schedule_date: str, score: float) -> None:
    """Write quality_score to the most recent confirmed schedule_log row."""
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
