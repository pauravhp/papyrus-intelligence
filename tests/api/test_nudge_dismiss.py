import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-client-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-client-secret")

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from api.auth import get_current_user
from api.config import settings
from api.main import app

FAKE_USER = {"sub": "user-123"}

@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def coaching_enabled(monkeypatch):
    """Turn the feature flag on for tests that exercise the live endpoint."""
    monkeypatch.setattr(settings, "COACHING_NUDGES_ENABLED", True)

client = TestClient(app)


@patch("api.routes.nudge.supabase")
def test_dismiss_per_instance(mock_sb, coaching_enabled):
    mock_sb.from_.return_value.upsert.return_value.execute.return_value = MagicMock()

    resp = client.post("/api/nudge/dismiss", json={
        "nudge_type": "repeated_deferral",
        "instance_key": "task-abc",
        "mode": "forever",
    })

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Verify upsert was called with correct payload including instance_key
    call_args = mock_sb.from_.return_value.upsert.call_args
    upserted = call_args[0][0]
    assert upserted["user_id"] == "user-123"
    assert upserted["nudge_type"] == "repeated_deferral"
    assert upserted["instance_key"] == "task-abc"


@patch("api.routes.nudge.supabase")
def test_dismiss_per_type_uses_sentinel(mock_sb, coaching_enabled):
    mock_sb.from_.return_value.upsert.return_value.execute.return_value = MagicMock()

    resp = client.post("/api/nudge/dismiss", json={
        "nudge_type": "repeated_deferral",
    })

    assert resp.status_code == 200
    call_args = mock_sb.from_.return_value.upsert.call_args
    upserted = call_args[0][0]
    # None instance_key → sentinel "__type__"
    assert upserted["instance_key"] == "__type__"


@patch("api.routes.nudge.supabase")
def test_dismiss_idempotent(mock_sb, coaching_enabled):
    """Double-dismiss same instance should not error."""
    mock_sb.from_.return_value.upsert.return_value.execute.return_value = MagicMock()

    for _ in range(2):
        resp = client.post("/api/nudge/dismiss", json={
            "nudge_type": "no_deadline",
            "instance_key": "task-xyz",
        })
        assert resp.status_code == 200


def test_dismiss_requires_auth(coaching_enabled):
    app.dependency_overrides.clear()
    try:
        resp = client.post("/api/nudge/dismiss", json={"nudge_type": "no_deadline"})
        assert resp.status_code in (401, 403, 422)
    finally:
        app.dependency_overrides[get_current_user] = lambda: FAKE_USER


def test_dismiss_404_when_flag_disabled():
    """With COACHING_NUDGES_ENABLED=False (default), the endpoint should 404."""
    resp = client.post("/api/nudge/dismiss", json={"nudge_type": "no_deadline"})
    assert resp.status_code == 404
