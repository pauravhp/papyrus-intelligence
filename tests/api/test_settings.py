# tests/api/test_settings.py
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
from api.main import app

FAKE_USER = {"sub": "user-123"}

# Override auth dependency for the entire module — no real JWT needed
@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    yield
    app.dependency_overrides.clear()

client = TestClient(app)


# ── /api/settings/nudges ──────────────────────────────────────────────────────

@patch("api.routes.settings.supabase")
def test_patch_nudges_sets_coaching_enabled(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch("/api/settings/nudges", json={"coaching_enabled": False})

    assert resp.status_code == 200
    assert resp.json()["nudges"]["coaching_enabled"] is False


@patch("api.routes.settings.supabase")
def test_patch_nudges_preserves_existing_keys(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"nudges": {"coaching_enabled": True, "weekly_reflection_enabled": True}}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch("/api/settings/nudges", json={"weekly_reflection_enabled": False})

    assert resp.status_code == 200
    nudges = resp.json()["nudges"]
    assert nudges["coaching_enabled"] is True        # untouched
    assert nudges["weekly_reflection_enabled"] is False


# ── /api/settings/calendars ───────────────────────────────────────────────────

@patch("api.routes.settings.supabase")
def test_patch_calendars_updates_source_and_write(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch(
        "/api/settings/calendars",
        json={"source_calendar_ids": ["cal-a", "cal-b"], "write_calendar_id": "cal-a"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_calendar_ids"] == ["cal-a", "cal-b"]
    assert data["write_calendar_id"] == "cal-a"


@patch("api.routes.settings.supabase")
def test_patch_calendars_preserves_existing_keys(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"source_calendar_ids": ["cal-x"], "write_calendar_id": "cal-x"}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch("/api/settings/calendars", json={"write_calendar_id": "cal-y"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_calendar_ids"] == ["cal-x"]  # untouched
    assert data["write_calendar_id"] == "cal-y"       # updated


def test_patch_calendars_requires_auth():
    # Clear the override to test real auth rejection
    app.dependency_overrides.clear()
    try:
        resp = client.patch("/api/settings/calendars", json={})
        assert resp.status_code in (401, 403, 422)
    finally:
        app.dependency_overrides[get_current_user] = lambda: FAKE_USER


@patch("api.routes.settings.supabase")
def test_patch_nudges_sets_disabled_types(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"nudges": {"coaching_enabled": True}}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch("/api/settings/nudges", json={"disabled_types": ["habit_skipped", "no_deadline"]})

    assert resp.status_code == 200
    nudges = resp.json()["nudges"]
    assert nudges["disabled_types"] == ["habit_skipped", "no_deadline"]
    assert nudges["coaching_enabled"] is True  # untouched


@patch("api.routes.settings.supabase")
def test_patch_nudges_disabled_types_replaces_full_list(mock_sb):
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"nudges": {"disabled_types": ["habit_skipped"]}}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.patch("/api/settings/nudges", json={"disabled_types": ["no_deadline"]})

    assert resp.status_code == 200
    nudges = resp.json()["nudges"]
    # Full replacement — not append
    assert nudges["disabled_types"] == ["no_deadline"]
    assert "habit_skipped" not in nudges["disabled_types"]
