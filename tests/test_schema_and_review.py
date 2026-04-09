"""
Unit tests for Phase-3 schema additions and review-flow helpers.
No API calls — all tests use a temporary SQLite database.

Test cases:
1. Migration idempotency — setup_database() is safe to call twice
2. time_of_day_bucket assignment — correct bucket for several scheduled_at times
3. session_number_today increment — sequential tasks get 1, 2, 3
4. estimated_vs_actual_ratio computation — correct value, NULL guard, div-by-zero guard
5. schedule_quality score — two scenarios checked
6. incomplete_reason stored correctly — mapped value and NULL for empty input
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

import src.db as db_module
from src.db import (
    _compute_time_bucket,
    compute_quality_score,
    get_connection,
    insert_task_history,
    set_incomplete_reason,
    setup_database,
    update_quality_score,
    upsert_task_completed,
)


# ── Fixture: isolated temp database ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Redirect DB_PATH to a temp directory for every test in this file."""
    original = db_module.DB_PATH
    db_module.DB_PATH = tmp_path / "test_schedule.db"
    setup_database()
    yield
    db_module.DB_PATH = original


# ── 1. Migration idempotency ───────────────────────────────────────────────────


def test_migration_idempotency():
    """Running setup_database() twice must not raise and must not duplicate columns."""
    setup_database()  # second call — already-existing columns must be silently skipped

    conn = get_connection()
    c = conn.cursor()

    # task_history columns
    c.execute("PRAGMA table_info(task_history)")
    th_cols = {row[1] for row in c.fetchall()}

    # schedule_log columns
    c.execute("PRAGMA table_info(schedule_log)")
    sl_cols = {row[1] for row in c.fetchall()}

    conn.close()

    expected_task_history = {
        "time_of_day_bucket", "window_type", "was_deep_work",
        "session_number_today", "back_to_back", "pre_meeting",
        "estimated_vs_actual_ratio", "incomplete_reason",
        "sync_source", "was_agent_scheduled", "mood_tag",
    }
    for col in expected_task_history:
        assert col in th_cols, f"task_history missing column: {col}"

    assert "quality_score" in sl_cols, "schedule_log missing column: quality_score"

    # Verify no duplicate column names (SQLite would raise on insert, but check anyway)
    c2 = get_connection().cursor()
    c2.execute("PRAGMA table_info(task_history)")
    all_names = [row[1] for row in c2.fetchall()]
    assert len(all_names) == len(set(all_names)), "Duplicate column names in task_history"


# ── 2. time_of_day_bucket assignment ──────────────────────────────────────────


@pytest.mark.parametrize("hour,minute,expected_bucket,expected_window", [
    (10, 45, "morning_peak",  "peak"),       # inside morning peak (10:30–14:30)
    (13, 30, "morning_peak",  "peak"),       # 13:30 still within morning peak
    (14, 30, "trough",        "trough"),     # exactly at morning_peak_end → trough starts
    (16, 0,  "trough",        "trough"),     # 16:00 still in trough (ends at 16:30)
    (16, 30, "afternoon_peak","secondary"),  # exactly at trough_end → afternoon_peak starts
    (17, 0,  "afternoon_peak","secondary"),  # inside afternoon_peak (16:30–18:00)
    (18, 0,  "evening",       "other"),      # exactly at evening boundary
    (22, 30, "late_night",    "other"),      # late night (≥21:00)
    (9,  0,  "late_night",    "other"),      # before first_task_not_before → late_night bucket
])
def test_time_of_day_bucket(hour, minute, expected_bucket, expected_window):
    """_compute_time_bucket returns correct (bucket, window_type) for various times.

    first_task_not_before = 10:30 → morning_peak [10:30, 14:30)
    """
    scheduled_at = f"2026-04-08T{hour:02d}:{minute:02d}:00"
    bucket, window = _compute_time_bucket(scheduled_at, first_task_not_before="10:30")
    assert bucket == expected_bucket, f"at {hour}:{minute:02d} expected bucket '{expected_bucket}', got '{bucket}'"
    assert window == expected_window, f"at {hour}:{minute:02d} expected window '{expected_window}', got '{window}'"


def test_time_bucket_returns_none_for_empty():
    """Empty or unparseable scheduled_at returns (None, None)."""
    assert _compute_time_bucket("") == (None, None)
    assert _compute_time_bucket("not-a-date") == (None, None)


# ── 3. session_number_today increment ─────────────────────────────────────────


def test_session_number_today_increments_per_date():
    """Tasks inserted for the same date get session_number_today = 1, 2, 3."""
    date_str = "2026-04-08"
    for i in range(3):
        insert_task_history(
            task_id=f"task-{i}",
            task_name=f"Task {i}",
            project_id="proj",
            estimated_duration_mins=30,
            scheduled_at=f"{date_str}T{10 + i}:30:00",
        )

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT session_number_today FROM task_history WHERE DATE(scheduled_at) = ? ORDER BY scheduled_at",
        (date_str,),
    )
    numbers = [row[0] for row in c.fetchall()]
    conn.close()

    assert numbers == [1, 2, 3], f"Expected [1, 2, 3], got {numbers}"


def test_session_number_resets_for_different_date():
    """A task on a different date gets session_number_today = 1 (not continuing)."""
    insert_task_history(
        task_id="day1-t1",
        task_name="Day 1 Task",
        project_id="proj",
        estimated_duration_mins=30,
        scheduled_at="2026-04-08T10:30:00",
    )
    insert_task_history(
        task_id="day2-t1",
        task_name="Day 2 Task",
        project_id="proj",
        estimated_duration_mins=30,
        scheduled_at="2026-04-09T10:30:00",
    )

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT task_id, session_number_today FROM task_history ORDER BY scheduled_at"
    )
    rows = {row[0]: row[1] for row in c.fetchall()}
    conn.close()

    assert rows["day1-t1"] == 1
    assert rows["day2-t1"] == 1, f"Expected 1 for day 2, got {rows['day2-t1']}"


# ── 4. estimated_vs_actual_ratio computation ──────────────────────────────────


def test_ratio_computed_correctly():
    """estimated=60, actual=90 → ratio=1.5."""
    insert_task_history(
        task_id="t-ratio",
        task_name="Ratio Task",
        project_id="proj",
        estimated_duration_mins=60,
        scheduled_at="2026-04-08T10:30:00",
    )
    upsert_task_completed(
        task_id="t-ratio",
        task_name="Ratio Task",
        project_id="proj",
        estimated_duration_mins=60,
        actual_duration_mins=90,
        completed_at="2026-04-08T12:00:00",
        scheduled_at="2026-04-08T10:30:00",
    )

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT estimated_vs_actual_ratio FROM task_history WHERE task_id = 't-ratio'")
    ratio = c.fetchone()[0]
    conn.close()

    assert ratio == pytest.approx(1.5), f"Expected 1.5, got {ratio}"


def test_ratio_stays_null_when_actual_is_null():
    """estimated=60, actual=NULL → ratio stays NULL."""
    insert_task_history(
        task_id="t-null-actual",
        task_name="No Actual",
        project_id="proj",
        estimated_duration_mins=60,
        scheduled_at="2026-04-08T10:30:00",
    )
    upsert_task_completed(
        task_id="t-null-actual",
        task_name="No Actual",
        project_id="proj",
        estimated_duration_mins=60,
        actual_duration_mins=None,
        completed_at="2026-04-08T12:00:00",
    )

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT estimated_vs_actual_ratio FROM task_history WHERE task_id = 't-null-actual'")
    ratio = c.fetchone()[0]
    conn.close()

    assert ratio is None


def test_ratio_stays_null_when_estimated_is_zero():
    """estimated=0, actual=30 → ratio stays NULL (avoid divide-by-zero)."""
    insert_task_history(
        task_id="t-zero-est",
        task_name="Zero Est",
        project_id="proj",
        estimated_duration_mins=0,
        scheduled_at="2026-04-08T10:30:00",
    )
    upsert_task_completed(
        task_id="t-zero-est",
        task_name="Zero Est",
        project_id="proj",
        estimated_duration_mins=0,
        actual_duration_mins=30,
        completed_at="2026-04-08T12:00:00",
    )

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT estimated_vs_actual_ratio FROM task_history WHERE task_id = 't-zero-est'")
    ratio = c.fetchone()[0]
    conn.close()

    assert ratio is None


# ── 5. schedule_quality score ─────────────────────────────────────────────────


def _insert_tasks_for_quality(tasks: list[dict]) -> None:
    """Helper: bulk-insert task_history rows for quality-score tests.

    Each dict must have: task_id, completed (bool), back_to_back (0/1),
    was_deep_work (0/1), window_type, reschedule_count, same_day_reschedule (bool).
    scheduled_at is always 2026-04-08.
    """
    date_str = "2026-04-08"
    conn = get_connection()
    c = conn.cursor()
    for t in tasks:
        # Use direct INSERT to bypass session_number_today SELECT
        scheduled_at = f"{date_str}T10:30:00"
        completed_at = f"{date_str}T12:00:00" if t.get("completed") else None
        # created_at: same day for same_day_reschedule, day before otherwise
        if t.get("same_day_reschedule"):
            created_at = f"{date_str}T08:00:00"
        else:
            created_at = "2026-04-07T08:00:00"
        c.execute(
            """
            INSERT INTO task_history (
                task_id, task_name, project_id, estimated_duration_mins,
                scheduled_at, completed_at, back_to_back, was_deep_work,
                window_type, reschedule_count, was_agent_scheduled, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                t["task_id"], t.get("task_name", t["task_id"]), "proj", 60,
                scheduled_at, completed_at,
                t.get("back_to_back", 0), t.get("was_deep_work", 0),
                t.get("window_type", "peak"),
                t.get("reschedule_count", 0),
                created_at,
            ),
        )
    conn.commit()
    conn.close()


def test_quality_score_basic_completion():
    """5 scheduled, 4 completed, no deductions → (4/5)*100 = 80.0."""
    tasks = [
        {"task_id": f"t{i}", "completed": i < 4, "back_to_back": 0, "was_deep_work": 0,
         "window_type": "peak", "reschedule_count": 0, "same_day_reschedule": False}
        for i in range(5)
    ]
    _insert_tasks_for_quality(tasks)

    score = compute_quality_score("2026-04-08")
    assert score == pytest.approx(80.0), f"Expected 80.0, got {score}"


def test_quality_score_with_same_day_reschedule():
    """4 scheduled, 2 completed, 1 same-day reschedule → (2/4)*100 - 5 = 45.0."""
    tasks = [
        {"task_id": "t0", "completed": True, "back_to_back": 0,
         "reschedule_count": 0, "same_day_reschedule": False},
        {"task_id": "t1", "completed": True, "back_to_back": 0,
         "reschedule_count": 0, "same_day_reschedule": False},
        {"task_id": "t2", "completed": False, "back_to_back": 0,
         "reschedule_count": 1, "same_day_reschedule": True},   # rescheduled same day
        {"task_id": "t3", "completed": False, "back_to_back": 0,
         "reschedule_count": 0, "same_day_reschedule": False},
    ]
    _insert_tasks_for_quality(tasks)

    score = compute_quality_score("2026-04-08")
    assert score == pytest.approx(45.0), f"Expected 45.0, got {score}"


def test_quality_score_no_tasks_returns_zero():
    """No tasks for date → score is 0.0."""
    score = compute_quality_score("2026-04-08")
    assert score == 0.0


def test_quality_score_not_inflated_after_reschedule():
    """
    Regression: rescheduled tasks must still count against today's score.

    8 tasks planned for 2026-04-08. 7 completed. 1 incomplete, then rescheduled
    to 2026-04-09 (scheduled_at changes via upsert). quality score must be
    computed BEFORE the reschedule write — using still-today scheduled_at values.
    Simulates the order: Step 3 (mark complete) → compute score → Step 4 (reschedule).
    """
    date_str = "2026-04-08"
    tomorrow_str = "2026-04-09"

    # Insert 8 tasks for today
    conn = get_connection()
    c = conn.cursor()
    for i in range(8):
        completed_at = f"{date_str}T12:00:00" if i < 7 else None
        c.execute(
            """
            INSERT INTO task_history (
                task_id, task_name, project_id, estimated_duration_mins,
                scheduled_at, completed_at, was_agent_scheduled, created_at
            ) VALUES (?, ?, 'proj', 60, ?, ?, 1, ?)
            """,
            (
                f"t{i}", f"Task {i}",
                f"{date_str}T10:30:00", completed_at,
                f"{date_str}T08:00:00",
            ),
        )
    conn.commit()

    # Score BEFORE reschedule — 7/8 = 87.5
    score_before = compute_quality_score(date_str)
    assert score_before == pytest.approx(87.5), f"Expected 87.5, got {score_before}"

    # Simulate reschedule write: upsert task 7's scheduled_at to tomorrow
    c.execute(
        "UPDATE task_history SET scheduled_at = ? WHERE task_id = 't7'",
        (f"{tomorrow_str}T10:30:00",),
    )
    conn.commit()
    conn.close()

    # Score AFTER reschedule — if computed now, only 7 tasks remain today → wrong 100.0
    score_after = compute_quality_score(date_str)
    assert score_after == pytest.approx(100.0), (
        "After reschedule, only completed tasks remain on today's date — "
        "this confirms the score must be captured BEFORE reschedule writes."
    )
    # The test documents why the score must be computed early in _cmd_review().


def test_quality_score_stored_in_schedule_log():
    """update_quality_score() writes to the most recent confirmed schedule_log row."""
    from src.db import insert_schedule_log

    insert_schedule_log(
        schedule_date="2026-04-08",
        proposed_json={"blocks": []},
        confirmed=True,
        confirmed_at="2026-04-08T09:00:00",
    )
    update_quality_score("2026-04-08", 72.5)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT quality_score FROM schedule_log WHERE schedule_date = '2026-04-08' ORDER BY id DESC LIMIT 1"
    )
    stored = c.fetchone()[0]
    conn.close()

    assert stored == pytest.approx(72.5)


# ── 6. incomplete_reason stored correctly ─────────────────────────────────────


def test_incomplete_reason_stored_for_mapped_input():
    """Reason '2' maps to 'motivation' and is persisted in task_history."""
    insert_task_history(
        task_id="t-reason",
        task_name="Reason Task",
        project_id="proj",
        estimated_duration_mins=60,
        scheduled_at="2026-04-08T10:30:00",
    )
    reason_map = {"1": "time", "2": "motivation", "3": "blocked", "4": "skipped"}
    set_incomplete_reason("t-reason", reason_map.get("2"))

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT incomplete_reason FROM task_history WHERE task_id = 't-reason'")
    stored = c.fetchone()[0]
    conn.close()

    assert stored == "motivation"


def test_incomplete_reason_null_for_empty_input():
    """Empty input (user pressed Enter) stores NULL, not empty string."""
    insert_task_history(
        task_id="t-no-reason",
        task_name="No Reason Task",
        project_id="proj",
        estimated_duration_mins=60,
        scheduled_at="2026-04-08T10:30:00",
    )
    reason_map = {"1": "time", "2": "motivation", "3": "blocked", "4": "skipped"}
    # Empty string → reason_map.get("") returns None
    set_incomplete_reason("t-no-reason", reason_map.get(""))

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT incomplete_reason FROM task_history WHERE task_id = 't-no-reason'")
    stored = c.fetchone()[0]
    conn.close()

    assert stored is None, f"Expected NULL, got '{stored}'"
