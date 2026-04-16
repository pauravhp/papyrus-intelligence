import os
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


def _mock_user_creds(sb, gcal_creds=None):
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = {"google_credentials": gcal_creds or {"token": "tok"}}


def _mock_user_config(sb, config=None):
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = {"config": config or {}, "google_credentials": {"token": "tok"}}


def test_get_calendars_returns_list(client, monkeypatch):
    """GET /api/calendars returns list of calendar objects."""
    mock_sb = MagicMock()
    _mock_user_creds(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    calendars = [
        {"id": "primary", "summary": "Personal", "background_color": "#4285f4", "access_role": "owner"},
        {"id": "work@co.com", "summary": "Work", "background_color": "#0b8043", "access_role": "writer"},
    ]

    with patch("api.routes.calendars.supabase", mock_sb), \
         patch("api.routes.calendars.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.calendars.list_calendars", return_value=calendars):
        resp = client.get("/api/calendars", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == "primary"
    assert data[1]["access_role"] == "writer"


def test_get_calendars_400_when_no_gcal_credentials(client, monkeypatch):
    """GET /api/calendars returns 400 if user has no GCal credentials."""
    mock_sb = MagicMock()
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = {"google_credentials": None}

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.calendars.supabase", mock_sb):
        resp = client.get("/api/calendars", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 400


def test_patch_calendar_settings_saves_to_config(client, monkeypatch):
    """PATCH /api/settings/calendars writes source_calendar_ids and write_calendar_id to config."""
    mock_sb = MagicMock()
    _mock_user_config(mock_sb, config={"user": {"timezone": "America/Vancouver"}})
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    writable_cals = [
        {"id": "primary", "summary": "Personal", "background_color": "#4285f4", "access_role": "owner"},
        {"id": "work@co.com", "summary": "Work", "background_color": "#0b8043", "access_role": "writer"},
    ]

    with patch("api.routes.calendars.supabase", mock_sb), \
         patch("api.routes.calendars.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.calendars.list_calendars", return_value=writable_cals):
        resp = client.patch(
            "/api/settings/calendars",
            json={"source_calendar_ids": ["primary", "work@co.com"], "write_calendar_id": "primary"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    update_call = mock_sb.from_.return_value.update.call_args
    saved_config = update_call.args[0]["config"]
    assert saved_config["source_calendar_ids"] == ["primary", "work@co.com"]
    assert saved_config["write_calendar_id"] == "primary"


def test_patch_calendar_settings_rejects_empty_source(client, monkeypatch):
    """PATCH /api/settings/calendars returns 422 for empty source_calendar_ids."""
    mock_sb = MagicMock()
    _mock_user_config(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.calendars.supabase", mock_sb), \
         patch("api.routes.calendars.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.calendars.list_calendars", return_value=[]):
        resp = client.patch(
            "/api/settings/calendars",
            json={"source_calendar_ids": []},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 422


def test_patch_calendar_settings_rejects_nonwritable_write_target(client, monkeypatch):
    """PATCH /api/settings/calendars returns 422 if write_calendar_id is read-only."""
    mock_sb = MagicMock()
    _mock_user_config(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    cals = [
        {"id": "primary", "access_role": "owner", "summary": "Personal", "background_color": "#4285f4"},
        {"id": "holidays", "access_role": "reader", "summary": "Holidays", "background_color": "#795548"},
    ]

    with patch("api.routes.calendars.supabase", mock_sb), \
         patch("api.routes.calendars.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.calendars.list_calendars", return_value=cals):
        resp = client.patch(
            "/api/settings/calendars",
            json={"source_calendar_ids": ["primary"], "write_calendar_id": "holidays"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 422


def test_patch_calendar_settings_nudge_dismissed(client, monkeypatch):
    """PATCH /api/settings/calendars with nudge_dismissed=true sets nudges.calendar_dismissed."""
    mock_sb = MagicMock()
    _mock_user_config(mock_sb, config={"user": {"timezone": "UTC"}})
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.calendars.supabase", mock_sb):
        resp = client.patch(
            "/api/settings/calendars",
            json={"nudge_dismissed": True},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    update_call = mock_sb.from_.return_value.update.call_args
    saved_config = update_call.args[0]["config"]
    assert saved_config["nudges"]["calendar_dismissed"] is True
