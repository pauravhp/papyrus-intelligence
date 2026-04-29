import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import json
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _mock_schedule_log(sb, tasks: list[dict], confirmed: bool = True):
    """Mock a schedule_log row with the given scheduled tasks.

    Chain mirrors the preflight query: from.select.eq.eq.eq.is_.order.execute
    (preflight no longer uses .limit; it iterates rows looking for usable data).
    """
    proposed = {"scheduled": tasks, "pushed": []}
    row = {"id": 1, "proposed_json": json.dumps(proposed), "confirmed": 1 if confirmed else 0}
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .execute.return_value
    ).data = [row]


def _mock_no_schedule(sb):
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .execute.return_value
    ).data = []


def _mock_rhythms(sb, rhythms: list[dict]):
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ).data = rhythms


SAMPLE_TASKS = [
    {
        "task_id": "t1",
        "task_name": "Deep work",
        "duration_minutes": 90,
        "start_time": "2026-04-15T09:00:00+05:30",
        "end_time": "2026-04-15T10:30:00+05:30",
    },
    {
        "task_id": "t2",
        "task_name": "Reply to emails",
        "duration_minutes": 30,
        "start_time": "2026-04-15T11:00:00+05:30",
        "end_time": "2026-04-15T11:30:00+05:30",
    },
]

SAMPLE_RHYTHMS = [{"id": 1, "rhythm_name": "Morning run"}]


def test_preflight_returns_tasks_with_todoist_completion_status(client, monkeypatch):
    """Tasks-section items are real Todoist tasks; the Rhythms section comes
    from scheduled[] entries with task_id starting "proj_". SAMPLE_TASKS has
    none of those, so rhythms is empty here. See the dedicated test below
    for the proj_<rhythm_id> split."""
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, SAMPLE_TASKS)
    _mock_rhythms(mock_sb, SAMPLE_RHYTHMS)

    mock_todoist = MagicMock()
    # t1 is completed in Todoist (get_task returns None for completed tasks)
    mock_todoist.get_task.side_effect = lambda task_id: None if task_id == "t1" else MagicMock(id=task_id)

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review.TodoistClient", return_value=mock_todoist):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 2
    t1 = next(t for t in data["tasks"] if t["task_id"] == "t1")
    t2 = next(t for t in data["tasks"] if t["task_id"] == "t2")
    assert t1["already_completed_in_todoist"] is True
    assert t2["already_completed_in_todoist"] is False
    assert t1["estimated_duration_mins"] == 90
    assert data["rhythms"] == []  # no proj_ tasks in SAMPLE_TASKS


def test_preflight_splits_proj_synthetic_tasks_into_rhythms_section(client, monkeypatch):
    """A scheduled item with task_id="proj_<rhythm_id>" is a synthetic rhythm
    task. It belongs in the Rhythms section so the submit writes
    rhythm_completions (not task_history). The Tasks section contains only
    real Todoist tasks. Each item is reviewed exactly once."""
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    tasks_with_synthetic = [
        {
            "task_id": "real_t1",
            "task_name": "Real Todoist task",
            "duration_minutes": 30,
            "start_time": "2026-04-15T09:00:00+05:30",
            "end_time": "2026-04-15T09:30:00+05:30",
        },
        {
            "task_id": "proj_42",
            "task_name": "Morning run",
            "duration_minutes": 30,
            "start_time": "2026-04-15T07:00:00+05:30",
            "end_time": "2026-04-15T07:30:00+05:30",
        },
    ]
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, tasks_with_synthetic)
    _mock_rhythms(mock_sb, [])  # active-rhythms list is now ignored by preflight

    mock_todoist = MagicMock()
    mock_todoist.get_task.return_value = MagicMock()

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review.TodoistClient", return_value=mock_todoist):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    # Real task only in Tasks section
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == "real_t1"
    # Synthetic rhythm only in Rhythms section, with rhythm_id parsed from task_id
    assert len(data["rhythms"]) == 1
    assert data["rhythms"][0] == {"id": 42, "rhythm_name": "Morning run"}


def test_preflight_404_when_no_confirmed_schedule(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    _mock_no_schedule(mock_sb)

    with patch("api.routes.review.supabase", mock_sb):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 404


def test_preflight_falls_back_gracefully_when_todoist_fails(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, SAMPLE_TASKS)
    _mock_rhythms(mock_sb, SAMPLE_RHYTHMS)

    mock_todoist = MagicMock()
    mock_todoist.get_task.side_effect = Exception("Todoist unavailable")

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review.TodoistClient", return_value=mock_todoist):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    # All tasks default to not completed when Todoist fails
    assert all(not t["already_completed_in_todoist"] for t in data["tasks"])


def test_submit_writes_task_history_rows(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []

    payload = {
        "tasks": [
            {
                "task_id": "t1",
                "task_name": "Deep work",
                "completed": True,
                "actual_duration_mins": 90,
                "estimated_duration_mins": 90,
                "scheduled_at": "2026-04-15T09:00:00+05:30",
                "incomplete_reason": None,
            }
        ],
        "rhythms": [],
    }

    with patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["saved"] is True
    # Verify upsert was called on task_history
    mock_sb.from_.assert_any_call("task_history")


def test_submit_writes_rhythm_completions(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []

    payload = {
        "tasks": [],
        "rhythms": [
            {"rhythm_id": 1, "completed": True},
            {"rhythm_id": 2, "completed": False},
        ],
    }

    with patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    # Verify upsert was called on rhythm_completions for completed rhythms only
    mock_sb.from_.assert_any_call("rhythm_completions")


def test_submit_is_idempotent_on_resubmit(client, monkeypatch):
    """Second submit with same data should not raise — upsert handles conflict."""
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []

    payload = {
        "tasks": [
            {
                "task_id": "t1",
                "task_name": "Deep work",
                "completed": True,
                "actual_duration_mins": 90,
                "estimated_duration_mins": 90,
                "scheduled_at": "2026-04-15T09:00:00+05:30",
                "incomplete_reason": None,
            }
        ],
        "rhythms": [],
    }

    with patch("api.routes.review.supabase", mock_sb):
        resp1 = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})
        resp2 = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_review_submit_fires_analytics(client, monkeypatch):
    from unittest.mock import patch
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []

    body = {
        "tasks": [{"task_id": "t1", "task_name": "Write code", "completed": True,
                   "actual_duration_mins": 60, "estimated_duration_mins": 60,
                   "scheduled_at": "2026-04-17T09:00:00", "incomplete_reason": None}],
        "rhythms": [{"rhythm_id": 1, "completed": True}],
    }
    with patch("api.routes.review.capture") as mock_capture, \
         patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=body, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 200
    mock_capture.assert_called_once()
    args = mock_capture.call_args[0]
    assert args[1] == "review_submitted"
    assert args[2]["tasks_total"] == 1
    assert args[2]["tasks_completed"] == 1
    assert args[2]["rhythms_total"] == 1
    assert args[2]["rhythms_completed"] == 1


def test_submit_uses_schedule_date_from_body(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []
    mock_sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = []

    payload = {
        "schedule_date": "2026-04-26",
        "tasks": [{
            "task_id": "t1", "task_name": "Deep work", "completed": True,
            "actual_duration_mins": 90, "estimated_duration_mins": 90,
            "scheduled_at": "2026-04-26T09:00:00+05:30", "incomplete_reason": None,
        }],
        "rhythms": [],
    }
    with patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    upsert_calls = [c for c in mock_sb.from_.return_value.upsert.call_args_list]
    assert any(
        rows[0].get("schedule_date") == "2026-04-26"
        for call in upsert_calls
        for rows in [call.args[0]] if isinstance(rows, list) and rows
    )


def test_submit_sets_reviewed_at_on_schedule_log_row(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []

    payload = {
        "schedule_date": "2026-04-27",
        "tasks": [], "rhythms": [],
    }
    with patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    mock_sb.from_.assert_any_call("schedule_log")
    update_calls = mock_sb.from_.return_value.update.call_args_list
    assert any("reviewed_at" in (c.args[0] if c.args else c.kwargs.get("json", {})) for c in update_calls)


def test_submit_rejects_future_date(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    future = (date.today() + timedelta(days=1)).isoformat()
    payload = {"schedule_date": future, "tasks": [], "rhythms": []}
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


def test_submit_rejects_date_older_than_7_days(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    old = (date.today() - timedelta(days=8)).isoformat()
    payload = {"schedule_date": old, "tasks": [], "rhythms": []}
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


def test_submit_response_no_longer_includes_summary_line(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    mock_sb.from_.return_value.upsert.return_value.execute.return_value.data = []
    payload = {"tasks": [], "rhythms": []}
    with patch("api.routes.review.supabase", mock_sb):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 200
    assert "summary_line" not in resp.json()
    assert resp.json() == {"saved": True}


def test_preflight_accepts_date_param(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, SAMPLE_TASKS)
    _mock_rhythms(mock_sb, SAMPLE_RHYTHMS)
    mock_todoist = MagicMock()
    mock_todoist.get_task.return_value = MagicMock()

    target = (date.today() - timedelta(days=2)).isoformat()
    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review.TodoistClient", return_value=mock_todoist):
        resp = client.get(f"/api/review/preflight?date={target}", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    # schedule_date is the second .eq in the chain: .select().eq(user_id).eq(schedule_date)
    eq2_calls = mock_sb.from_.return_value.select.return_value.eq.return_value.eq.call_args_list
    assert any(call.args == ("schedule_date", target) for call in eq2_calls)


def test_preflight_rejects_future_date(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    future = (date.today() + timedelta(days=1)).isoformat()
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.get(f"/api/review/preflight?date={future}", headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


# ── Preflight defensive row selection ─────────────────────────────────────────


def _mock_schedule_log_rows(sb, rows: list[dict]):
    """Mock the preflight query to return a specific list of rows (DESC id)."""
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .execute.return_value
    ).data = rows


def test_preflight_skips_junk_rows_and_uses_first_valid_one(client, monkeypatch):
    """If the highest-id row has null/empty proposed_json, preflight falls back
    to the next row that actually has scheduled tasks. Without this the user is
    stranded — review_queue keeps offering the day but preflight 404s."""
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    valid_proposed = json.dumps({"scheduled": SAMPLE_TASKS, "pushed": []})
    rows = [
        {"id": 99, "proposed_json": None},               # null — skip
        {"id": 50, "proposed_json": ""},                  # empty string — skip
        {"id": 40, "proposed_json": "{}"},                # decodes to dict but no scheduled — skip
        {"id": 30, "proposed_json": valid_proposed},     # valid — use this
    ]
    mock_sb = MagicMock()
    _mock_schedule_log_rows(mock_sb, rows)
    _mock_rhythms(mock_sb, [])
    mock_todoist = MagicMock()
    mock_todoist.get_task.return_value = MagicMock()

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review.TodoistClient", return_value=mock_todoist):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == len(SAMPLE_TASKS)


def test_preflight_404_when_all_rows_have_unusable_proposed_json(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    rows = [
        {"id": 99, "proposed_json": None},
        {"id": 50, "proposed_json": "{}"},
        {"id": 40, "proposed_json": json.dumps({"scheduled": []})},
    ]
    mock_sb = MagicMock()
    _mock_schedule_log_rows(mock_sb, rows)

    with patch("api.routes.review.supabase", mock_sb):
        resp = client.get("/api/review/preflight", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 404
