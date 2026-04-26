import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-client-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-client-secret")
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
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"user": {"timezone": "America/Vancouver"}}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.settings.supabase", mock_sb):
        resp = client.patch(
            "/api/settings/calendars",
            json={"source_calendar_ids": ["primary", "work@co.com"], "write_calendar_id": "primary"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_calendar_ids"] == ["primary", "work@co.com"]
    assert data["write_calendar_id"] == "primary"

    update_call = mock_sb.from_.return_value.update.call_args
    saved_config = update_call.args[0]["config"]
    assert saved_config["source_calendar_ids"] == ["primary", "work@co.com"]
    assert saved_config["write_calendar_id"] == "primary"


def test_patch_calendar_settings_saves_calendar_rules(client, monkeypatch):
    """PATCH /api/settings/calendars writes calendar_rules to config."""
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    rules = {"work@co.com": {"exclude": True}}
    with patch("api.routes.settings.supabase", mock_sb):
        resp = client.patch(
            "/api/settings/calendars",
            json={"calendar_rules": rules},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    assert resp.json()["calendar_rules"] == rules


def test_patch_calendar_settings_partial_update(client, monkeypatch):
    """PATCH /api/settings/calendars with only write_calendar_id does not overwrite source_calendar_ids."""
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"config": {"source_calendar_ids": ["primary"]}}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.settings.supabase", mock_sb):
        resp = client.patch(
            "/api/settings/calendars",
            json={"write_calendar_id": "primary"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_calendar_ids"] == ["primary"]   # preserved from existing config
    assert data["write_calendar_id"] == "primary"


def test_patch_calendar_settings_requires_auth(client):
    """PATCH /api/settings/calendars returns 401/403/422 without auth token."""
    resp = client.patch("/api/settings/calendars", json={})
    assert resp.status_code in (401, 403, 422)
