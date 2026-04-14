import os, json
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _mock_schedule_log(sb, rows):
    """Configure supabase mock to return schedule_log rows."""
    chain = (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .eq.return_value
        .order.return_value
        .execute.return_value
    )
    chain.data = rows


def test_get_today_returns_three_days(client, monkeypatch):
    """GET /api/today returns yesterday/today/tomorrow keys."""
    from datetime import date, timedelta
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

    schedule = {
        "scheduled": [{"task_id": "1", "task_name": "Deep work", "start_time": f"{today_str}T09:00:00-07:00", "end_time": f"{today_str}T10:30:00-07:00", "duration_minutes": 90}],
        "pushed": [],
        "reasoning_summary": "Scheduled for focus time."
    }
    rows = [{"schedule_date": today_str, "proposed_json": json.dumps(schedule), "confirmed_at": f"{today_str}T08:00:00Z"}]

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, rows)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert "yesterday" in data
    assert "today" in data
    assert "tomorrow" in data
    assert data["today"]["schedule_date"] == today_str
    assert len(data["today"]["scheduled"]) == 1
    assert data["yesterday"] is None
    assert data["tomorrow"] is None


def test_get_today_handles_no_schedule(client, monkeypatch):
    """GET /api/today returns None for all days when no confirmed schedules."""
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, [])

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["yesterday"] is None
    assert data["today"] is None
    assert data["tomorrow"] is None
