import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock
from api.services.review_aggregate_service import compute_per_day_stats


def test_compute_per_day_stats_counts_partial_completion():
    sb = MagicMock()
    th_rows = [
        {"schedule_date": "2026-04-26", "task_id": "a", "completed_at": "2026-04-26T09:00:00Z"},
        {"schedule_date": "2026-04-26", "task_id": "b", "completed_at": "2026-04-26T10:00:00Z"},
        {"schedule_date": "2026-04-26", "task_id": "c", "completed_at": None},
        {"schedule_date": "2026-04-27", "task_id": "d", "completed_at": "2026-04-27T09:00:00Z"},
    ]
    rc_rows = [
        {"completed_on": "2026-04-26", "rhythm_id": 1},
    ]
    rhythms_rows = [{"id": 1, "rhythm_name": "Run"}, {"id": 2, "rhythm_name": "Read"}]

    sb.from_.side_effect = lambda table: _table_mock(table, th_rows, rc_rows, rhythms_rows)
    out = compute_per_day_stats("user-1", ["2026-04-26", "2026-04-27"], sb)

    assert len(out) == 2
    day1 = next(d for d in out if d["schedule_date"] == "2026-04-26")
    assert day1["tasks_completed"] == 2
    assert day1["tasks_total"] == 3
    assert day1["rhythms_completed"] == 1
    assert day1["rhythms_total"] == 2
    day2 = next(d for d in out if d["schedule_date"] == "2026-04-27")
    assert day2["tasks_completed"] == 1
    assert day2["tasks_total"] == 1


def test_compute_per_day_stats_handles_no_tasks_or_rhythms():
    sb = MagicMock()
    sb.from_.side_effect = lambda table: _table_mock(table, [], [], [])
    out = compute_per_day_stats("user-1", ["2026-04-27"], sb)
    assert len(out) == 1
    assert out[0]["tasks_total"] == 0
    assert out[0]["tasks_completed"] == 0
    assert out[0]["rhythms_total"] == 0
    assert out[0]["rhythms_completed"] == 0


def test_compute_per_day_stats_empty_dates_returns_empty():
    sb = MagicMock()
    out = compute_per_day_stats("user-1", [], sb)
    assert out == []


def _table_mock(table, th_rows, rc_rows, rhythms_rows):
    m = MagicMock()
    data = {"task_history": th_rows, "rhythm_completions": rc_rows, "rhythms": rhythms_rows}.get(table, [])
    m.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = data
    m.select.return_value.eq.return_value.execute.return_value.data = data
    return m
