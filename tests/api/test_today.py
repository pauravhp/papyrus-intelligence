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


def test_today_response_includes_review_available_false_before_cutoff(client):
    """review_available is False when current time is before sleep_time - 2.5h."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {
            "user": {"timezone": "America/New_York", "sleep_time": "23:00"},
            "rules": {"hard": []},
        },
    }
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]
    # 18:00 UTC = 14:00 ET — before cutoff of 20:30 ET
    mock_now = datetime(2026, 4, 15, 18, 0, 0, tzinfo=timezone.utc)

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is False


def test_today_response_includes_review_available_true_after_cutoff(client):
    """review_available is True when current time is at or after sleep_time - 2.5h."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {
            "user": {"timezone": "America/New_York", "sleep_time": "23:00"},
            "rules": {"hard": []},
        },
    }
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]
    # 01:00 UTC next day = 21:00 ET — after cutoff of 20:30 ET
    mock_now = datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc)

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is True


def test_today_review_available_false_when_no_confirmed_schedule(client):
    """review_available is False even after cutoff if no confirmed schedule exists."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {"user": {"timezone": "America/New_York"}, "rules": {"hard": []}},
    }
    # No confirmed schedule
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    mock_now = datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc)  # after cutoff

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is False
