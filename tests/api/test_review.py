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
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _mock_schedule_log(sb, tasks: list[dict], confirmed: bool = True):
    """Mock a schedule_log row with the given scheduled tasks (3-eq chain)."""
    proposed = {"scheduled": tasks, "pushed": []}
    row = {"proposed_json": json.dumps(proposed), "confirmed": 1 if confirmed else 0}
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]


def _mock_no_schedule(sb):
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
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
    assert len(data["rhythms"]) == 1
    assert data["rhythms"][0]["rhythm_name"] == "Morning run"


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

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review._generate_summary_line", return_value="Great work today."):
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

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review._generate_summary_line", return_value="Solid effort."):
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

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review._generate_summary_line", return_value="Good day."):
        resp1 = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})
        resp2 = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200


def test_submit_summary_line_fallback_on_llm_failure(client, monkeypatch):
    """summary_line falls back to static template if LLM call fails."""
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

    with patch("api.routes.review.supabase", mock_sb), \
         patch("api.routes.review._generate_summary_line", side_effect=Exception("LLM error")):
        resp = client.post("/api/review/submit", json=payload, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert "1 of 1" in resp.json()["summary_line"]  # static fallback
