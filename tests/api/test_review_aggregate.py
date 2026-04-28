import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def test_aggregate_returns_per_day_rows_and_narrative(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    payload = {"schedule_dates": ["2026-04-26", "2026-04-27"]}
    with patch("api.routes.review.compute_per_day_stats") as mock_stats, \
         patch("api.routes.review.compute_task_detail", return_value={}), \
         patch("api.routes.review.generate_aggregate_narrative", return_value="A calm two-day stretch."), \
         patch("api.routes.review.supabase", MagicMock()):
        mock_stats.return_value = [
            {"schedule_date": "2026-04-26", "weekday": "Sun", "tasks_completed": 2, "tasks_total": 3, "rhythms_completed": 1, "rhythms_total": 2},
            {"schedule_date": "2026-04-27", "weekday": "Mon", "tasks_completed": 1, "tasks_total": 1, "rhythms_completed": 0, "rhythms_total": 0},
        ]
        resp = client.post("/api/review/aggregate", json=payload, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative_line"] == "A calm two-day stretch."
    assert len(data["per_day"]) == 2
    assert data["per_day"][0]["weekday"] == "Sun"


def test_aggregate_rejects_empty_dates(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/aggregate", json={"schedule_dates": []}, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


def test_aggregate_rejects_more_than_7_dates(client, monkeypatch):
    from datetime import date, timedelta
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    dates = [(date.today() - timedelta(days=i)).isoformat() for i in range(8)]
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/aggregate", json={"schedule_dates": dates}, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


def test_aggregate_rejects_dates_outside_window(client, monkeypatch):
    from datetime import date, timedelta
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    old = (date.today() - timedelta(days=8)).isoformat()
    with patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/aggregate", json={"schedule_dates": [old]}, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 400


def test_aggregate_fires_telemetry(client, monkeypatch):
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    with patch("api.routes.review.compute_per_day_stats", return_value=[{"schedule_date": "2026-04-27", "weekday": "Mon", "tasks_completed": 1, "tasks_total": 1, "rhythms_completed": 0, "rhythms_total": 0}]), \
         patch("api.routes.review.compute_task_detail", return_value={}), \
         patch("api.routes.review.generate_aggregate_narrative", return_value="ok"), \
         patch("api.routes.review.capture") as mock_capture, \
         patch("api.routes.review.supabase", MagicMock()):
        resp = client.post("/api/review/aggregate", json={"schedule_dates": ["2026-04-27"]}, headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 200
    mock_capture.assert_called_once()
    assert mock_capture.call_args[0][1] == "review_queue_completed"
