"""
tests/test_sync.py — unit tests for --sync drift detection.

All tests use a temp SQLite database (no real API calls).
Todoist client methods are mocked via unittest.mock.patch.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import src.db as db_module
from src.db import (
    append_sync_diff,
    get_task_history_for_sync,
    get_task_ids_for_date,
    insert_task_history,
    setup_database,
    sync_apply_case_a,
    sync_apply_case_b,
    sync_apply_case_c,
    sync_inject_task,
)
from src.models import TodoistTask


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_sync.db")
    setup_database()


def _make_task(
    task_id: str,
    content: str = "Test task",
    due_datetime: datetime | None = None,
    duration_minutes: int | None = 60,
    project_id: str = "proj1",
    priority: int = 2,
) -> TodoistTask:
    return TodoistTask(
        id=task_id,
        content=content,
        project_id=project_id,
        priority=priority,
        due_datetime=due_datetime,
        deadline=None,
        duration_minutes=duration_minutes,
        labels=[],
        is_inbox=False,
    )


_TODAY = date(2026, 4, 9)
_TODAY_STR = _TODAY.isoformat()
_SCHED_AT = "2026-04-09T10:30:00"   # local naive ISO


def _insert_row(
    task_id: str = "task1",
    task_name: str = "Task One",
    scheduled_at: str = _SCHED_AT,
    completed_at: str | None = None,
    was_agent_scheduled: int = 1,
):
    insert_task_history(
        task_id=task_id,
        task_name=task_name,
        project_id="proj1",
        estimated_duration_mins=60,
        scheduled_at=scheduled_at,
        day_of_week="Wednesday",
        was_agent_scheduled=was_agent_scheduled,
        sync_source="agent",
    )
    if completed_at is not None:
        # insert_task_history doesn't include completed_at in its INSERT —
        # set it directly via SQL to simulate a previously-reviewed row.
        conn = db_module.get_connection()
        conn.execute(
            "UPDATE task_history SET completed_at = ? WHERE task_id = ?",
            (completed_at, task_id),
        )
        conn.commit()
        conn.close()


# ── DB function tests ─────────────────────────────────────────────────────────


def test_get_task_history_for_sync_returns_agent_rows():
    _insert_row(task_id="t1", was_agent_scheduled=1)
    _insert_row(task_id="t2", was_agent_scheduled=0)  # user-injected, excluded
    rows = get_task_history_for_sync(_TODAY_STR)
    ids = {r["task_id"] for r in rows}
    assert "t1" in ids
    assert "t2" not in ids


def test_get_task_history_for_sync_includes_null_was_agent_scheduled():
    """Backward compat: NULL was_agent_scheduled is treated as 1."""
    # Insert manually with NULL was_agent_scheduled
    import sqlite3
    conn = db_module.get_connection()
    conn.execute(
        "INSERT INTO task_history (task_id, task_name, scheduled_at) VALUES (?, ?, ?)",
        ("legacy", "Legacy task", _SCHED_AT),
    )
    conn.commit()
    conn.close()
    rows = get_task_history_for_sync(_TODAY_STR)
    ids = {r["task_id"] for r in rows}
    assert "legacy" in ids


def test_get_task_ids_for_date_returns_all_regardless_of_agent():
    _insert_row(task_id="agent_task", was_agent_scheduled=1)
    _insert_row(task_id="user_task", was_agent_scheduled=0)
    ids = get_task_ids_for_date(_TODAY_STR)
    assert "agent_task" in ids
    assert "user_task" in ids


def test_sync_apply_case_a_updates_time_and_reschedule_count():
    _insert_row(task_id="t1", scheduled_at=_SCHED_AT)
    new_time = "2026-04-09T14:00:00"
    sync_apply_case_a("t1", _TODAY_STR, new_time)
    rows = get_task_history_for_sync(_TODAY_STR)
    row = next(r for r in rows if r["task_id"] == "t1")
    assert row["scheduled_at"] == new_time
    assert row["reschedule_count"] == 1
    assert row["was_rescheduled"] == 1
    assert row["sync_source"] == "manual"


def test_sync_apply_case_b_sets_was_agent_scheduled_zero():
    _insert_row(task_id="t1")
    sync_apply_case_b("t1", _TODAY_STR)
    # Row should be excluded from get_task_history_for_sync (was_agent_scheduled=0)
    rows = get_task_history_for_sync(_TODAY_STR)
    assert all(r["task_id"] != "t1" for r in rows)
    # But it still exists in the DB (historical record)
    ids = get_task_ids_for_date(_TODAY_STR)
    assert "t1" in ids


def test_sync_apply_case_c_sets_completed_at_leaves_duration_null():
    _insert_row(task_id="t1")
    now_str = datetime.now().isoformat()
    sync_apply_case_c("t1", _TODAY_STR, now_str)

    import sqlite3
    conn = db_module.get_connection()
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute(
        "SELECT * FROM task_history WHERE task_id = ?", ("t1",)
    ).fetchone())
    conn.close()

    assert row["completed_at"] is not None
    assert row["actual_duration_mins"] is None  # NOT set by sync
    assert row["sync_source"] == "sync"


def test_sync_apply_case_c_does_not_overwrite_existing_completed():
    _insert_row(task_id="t1", completed_at="2026-04-09T12:00:00")
    sync_apply_case_c("t1", _TODAY_STR, "2026-04-09T15:00:00")

    import sqlite3
    conn = db_module.get_connection()
    row = conn.execute(
        "SELECT completed_at FROM task_history WHERE task_id = ?", ("t1",)
    ).fetchone()
    conn.close()
    assert row[0] == "2026-04-09T12:00:00"  # unchanged


def test_sync_inject_task_inserts_with_correct_flags():
    sync_inject_task(
        task_id="injected1",
        task_name="User task",
        project_id="proj1",
        estimated_duration_mins=30,
        scheduled_at="2026-04-09T16:00:00",
    )
    import sqlite3
    conn = db_module.get_connection()
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute(
        "SELECT * FROM task_history WHERE task_id = ?", ("injected1",)
    ).fetchone())
    conn.close()
    assert row["was_agent_scheduled"] == 0
    assert row["sync_source"] == "user_injected"
    assert row["estimated_duration_mins"] == 30


def test_sync_inject_task_on_conflict_does_nothing():
    """Injecting same task_id twice is a no-op (idempotent)."""
    sync_inject_task("t_dup", "Task", "p", 60, _SCHED_AT)
    sync_inject_task("t_dup", "Task updated", "p", 90, _SCHED_AT)
    import sqlite3
    conn = db_module.get_connection()
    row = conn.execute(
        "SELECT estimated_duration_mins FROM task_history WHERE task_id = ?", ("t_dup",)
    ).fetchone()
    conn.close()
    assert row[0] == 60  # first insert wins


def test_append_sync_diff_writes_to_schedule_log():
    from src.db import insert_schedule_log
    insert_schedule_log(
        schedule_date=_TODAY_STR,
        proposed_json={"scheduled": []},
        confirmed=True,
        confirmed_at=datetime.now().isoformat(),
    )
    changes = [{"task_id": "t1", "case": "A", "from": "10:30", "to": "14:00"}]
    append_sync_diff(_TODAY_STR, changes)

    import sqlite3
    import json
    conn = db_module.get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT diff_json FROM schedule_log WHERE schedule_date = ? ORDER BY id DESC LIMIT 1",
        (_TODAY_STR,),
    ).fetchone()
    conn.close()

    diff = json.loads(row["diff_json"])
    assert "sync_changes" in diff
    assert len(diff["sync_changes"]) == 1
    assert diff["sync_changes"][0]["changes"][0]["case"] == "A"


def test_append_sync_diff_noop_when_no_confirmed_row():
    """No error when no confirmed schedule_log row exists."""
    append_sync_diff(_TODAY_STR, [{"task_id": "t1", "case": "A"}])  # should not raise


# ── _cmd_sync integration tests ────────────────────────────────────────────────


def _context():
    return {"user": {"timezone": "America/Vancouver"}}


def _make_sync_client(tasks_by_id: dict[str, "TodoistTask | None | Exception"]) -> MagicMock:
    """Build a mock TodoistClient where get_task_by_id returns from tasks_by_id."""
    client = MagicMock()

    def _get(task_id):
        result = tasks_by_id.get(task_id, MagicMock())
        if isinstance(result, Exception):
            raise result
        return result

    client.get_task_by_id.side_effect = _get
    client.get_todays_scheduled_tasks.return_value = []
    return client


def _run_sync(context, target_date, silent=False):
    """Import and run _cmd_sync within the test process."""
    import main as main_module
    return main_module._cmd_sync(context, target_date, silent=silent)


class TestCaseA:
    def test_time_moved_same_day(self):
        """Case A: Todoist shows same-day task but different time (>5 min)."""
        _insert_row(task_id="t1", scheduled_at="2026-04-09T10:30:00")

        new_dt = datetime(2026, 4, 9, 14, 0, 0)
        mock_task = _make_task("t1", due_datetime=new_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": mock_task})
            result = _run_sync(_context(), _TODAY)

        assert result["moved"] == 1
        assert result["unchanged"] == 0

        rows = get_task_history_for_sync(_TODAY_STR)
        row = next(r for r in rows if r["task_id"] == "t1")
        assert "14:00" in row["scheduled_at"]
        assert row["reschedule_count"] == 1
        assert row["sync_source"] == "manual"

    def test_no_drift_within_5_minutes(self):
        """Case D: time difference < 5 min → no update."""
        _insert_row(task_id="t1", scheduled_at="2026-04-09T10:30:00")

        # 3 minutes later — within tolerance
        new_dt = datetime(2026, 4, 9, 10, 33, 0)
        mock_task = _make_task("t1", due_datetime=new_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": mock_task})
            result = _run_sync(_context(), _TODAY)

        assert result["moved"] == 0
        assert result["unchanged"] == 1

        rows = get_task_history_for_sync(_TODAY_STR)
        row = next(r for r in rows if r["task_id"] == "t1")
        assert "10:30" in row["scheduled_at"]  # unchanged
        assert row["reschedule_count"] == 0


class TestCaseB:
    def test_moved_to_different_day(self):
        """Case B: Todoist shows task due tomorrow → mark was_agent_scheduled=0."""
        _insert_row(task_id="t1", scheduled_at="2026-04-09T10:30:00")

        tomorrow_dt = datetime(2026, 4, 10, 10, 30, 0)
        mock_task = _make_task("t1", due_datetime=tomorrow_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": mock_task})
            result = _run_sync(_context(), _TODAY)

        assert result["moved"] == 1

        # Row still exists but was_agent_scheduled=0
        ids = get_task_ids_for_date(_TODAY_STR)
        assert "t1" in ids
        rows_for_sync = get_task_history_for_sync(_TODAY_STR)
        assert all(r["task_id"] != "t1" for r in rows_for_sync)  # excluded from sync view

    def test_due_date_cleared(self):
        """Case B: due_datetime is None (user unscheduled it) → same as moved away."""
        _insert_row(task_id="t1")

        mock_task = _make_task("t1", due_datetime=None)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": mock_task})
            result = _run_sync(_context(), _TODAY)

        assert result["moved"] == 1
        ids = get_task_ids_for_date(_TODAY_STR)
        assert "t1" in ids  # row preserved as historical record


class TestCaseC:
    def test_completed_outside_review(self):
        """Case C: 404 → task completed/deleted in Todoist, mark completed_at in DB."""
        _insert_row(task_id="t1")  # completed_at IS NULL

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": None})  # 404
            result = _run_sync(_context(), _TODAY)

        assert result["completed_outside"] == 1

        import sqlite3
        conn = db_module.get_connection()
        row = conn.execute(
            "SELECT completed_at, actual_duration_mins FROM task_history WHERE task_id = ?",
            ("t1",),
        ).fetchone()
        conn.close()

        assert row[0] is not None         # completed_at set
        assert row[1] is None             # actual_duration_mins NOT set (unknown)

    def test_already_reviewed_task_is_unchanged(self):
        """A task with completed_at already set is treated as Case D — no re-marking."""
        _insert_row(task_id="t1", completed_at="2026-04-09T12:00:00")

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": None})
            result = _run_sync(_context(), _TODAY)

        # completed_at was already set → counted as unchanged, not completed_outside
        assert result["completed_outside"] == 0
        assert result["unchanged"] == 1


class TestCaseD:
    def test_no_update_statements_on_clean_match(self):
        """Case D: exact match within 5 min → zero DB writes."""
        _insert_row(task_id="t1", scheduled_at="2026-04-09T10:30:00")

        same_dt = datetime(2026, 4, 9, 10, 30, 0)
        mock_task = _make_task("t1", due_datetime=same_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = _make_sync_client({"t1": mock_task})
            result = _run_sync(_context(), _TODAY)

        assert result["moved"] == 0
        assert result["unchanged"] == 1
        rows = get_task_history_for_sync(_TODAY_STR)
        row = next(r for r in rows if r["task_id"] == "t1")
        assert row["reschedule_count"] == 0


class TestUserInjected:
    def test_user_scheduled_task_added_to_history(self):
        """Step 4: Todoist has a task not in task_history → inject with was_agent_scheduled=0."""
        # No rows in task_history for today
        injected_dt = datetime(2026, 4, 9, 15, 0, 0)
        injected_task = _make_task("inject1", content="My manual task", due_datetime=injected_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            mock_client = MagicMock()
            mock_client.get_task_by_id.side_effect = lambda tid: None  # no rows to sync
            mock_client.get_todays_scheduled_tasks.return_value = [injected_task]
            MockClient.return_value = mock_client
            result = _run_sync(_context(), _TODAY)

        assert result["injected"] == 1

        import sqlite3
        conn = db_module.get_connection()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM task_history WHERE task_id = ?", ("inject1",)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["was_agent_scheduled"] == 0
        assert row["sync_source"] == "user_injected"

    def test_existing_task_not_re_injected(self):
        """A task already in task_history is not injected again."""
        _insert_row(task_id="t1")

        injected_dt = datetime(2026, 4, 9, 15, 0, 0)
        existing_task = _make_task("t1", due_datetime=injected_dt)
        same_dt = datetime(2026, 4, 9, 10, 30, 0)
        known_task = _make_task("t1", due_datetime=same_dt)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            mock_client = MagicMock()
            mock_client.get_task_by_id.return_value = known_task
            mock_client.get_todays_scheduled_tasks.return_value = [existing_task]
            MockClient.return_value = mock_client
            result = _run_sync(_context(), _TODAY)

        assert result["injected"] == 0


class TestEmptySchedule:
    def test_empty_schedule_returns_cleanly(self):
        """No task_history rows → returns zero counts, no crash."""
        with patch("src.todoist_client.TodoistClient") as MockClient:
            MockClient.return_value = MagicMock()
            result = _run_sync(_context(), _TODAY)

        assert result == {"moved": 0, "completed_outside": 0, "injected": 0, "unchanged": 0}


class TestRateLimit:
    def test_429_retry_succeeds(self):
        """First Todoist call raises 429 → retry once → returns task correctly."""
        import requests

        _insert_row(task_id="t1", scheduled_at="2026-04-09T10:30:00")

        same_dt = datetime(2026, 4, 9, 10, 30, 0)
        good_task = _make_task("t1", due_datetime=same_dt)

        # Simulate: first call raises 429, second call succeeds
        call_count = {"n": 0}

        def _get_with_429(task_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                resp = MagicMock()
                resp.status_code = 429
                raise requests.exceptions.HTTPError(response=resp)
            return good_task

        with patch("src.todoist_client.TodoistClient") as MockClient:
            mock_client = MagicMock()
            mock_client.get_task_by_id.side_effect = _get_with_429
            mock_client.get_todays_scheduled_tasks.return_value = []
            MockClient.return_value = mock_client

            with patch("time.sleep"):  # don't actually sleep in tests
                result = _run_sync(_context(), _TODAY)

        assert result["unchanged"] == 1  # processed correctly after retry
        assert call_count["n"] == 2

    def test_double_429_skips_task(self):
        """Two consecutive 429s → task is skipped (not crashed, not counted)."""
        import requests

        _insert_row(task_id="t1")

        def _always_429(_task_id):
            resp = MagicMock()
            resp.status_code = 429
            raise requests.exceptions.HTTPError(response=resp)

        with patch("src.todoist_client.TodoistClient") as MockClient:
            mock_client = MagicMock()
            mock_client.get_task_by_id.side_effect = _always_429
            mock_client.get_todays_scheduled_tasks.return_value = []
            MockClient.return_value = mock_client

            with patch("time.sleep"):
                result = _run_sync(_context(), _TODAY)

        # Not counted in any bucket — but no crash
        assert result["moved"] == 0
        assert result["completed_outside"] == 0


class TestAutoCallFromReview:
    def test_sync_runs_before_review_output(self, capsys):
        """
        Regression: sync must update task_history BEFORE review reads it.
        If task completed outside review (Case C), get_todays_task_history
        should not include it in the review prompt.
        """
        _insert_row(task_id="t1")  # completed_at = NULL

        # Sync: Todoist returns 404 (completed outside review)
        with patch("src.todoist_client.TodoistClient") as MockClient:
            mock_client = MagicMock()
            mock_client.get_task_by_id.return_value = None  # 404
            mock_client.get_todays_scheduled_tasks.return_value = []
            MockClient.return_value = mock_client
            _run_sync(_context(), _TODAY, silent=True)

        # After sync: get_todays_task_history should NOT return t1
        # (completed_at is now set, so it's filtered out)
        from src.db import get_todays_task_history
        remaining = get_todays_task_history(_TODAY_STR)
        assert all(r["task_id"] != "t1" for r in remaining)
