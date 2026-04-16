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


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _auth_header():
    return {"Authorization": "Bearer fake-jwt"}


def _mock_verify(monkeypatch):
    monkeypatch.setattr(
        "api.auth.verify_token",
        lambda token: {"sub": "user-uuid-123"},
    )


def test_scan_returns_proposed_config(client, monkeypatch):
    """scan reads GCal credentials from Supabase and returns proposed_config."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={
            "google_credentials": {
                "token": "tok",
                "refresh_token": "rref",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "cid",
                "client_secret": "cs",
                "scopes": ["https://www.googleapis.com/auth/calendar.events"],
            },
        }
    )

    mock_proposed = {"sleep": {"default_wake_time": "07:00"}, "calendar_rules": {}}

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials",
               return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call",
               return_value={"proposed_config": mock_proposed, "questions_for_stage_2": [], "detected_categories": []}):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "proposed_config" in data
    assert "questions" in data
    assert "detected_categories" in data


def test_scan_raises_400_if_no_gcal_creds(client, monkeypatch):
    """scan returns 400 if google_credentials not set for the user."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": None}
    )

    with patch("api.routes.onboard.supabase", mock_sb):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 400


def test_scan_400_on_gcal_token_refresh_failure(client, monkeypatch):
    """scan returns 400 if GCal token refresh fails (RuntimeError)."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials",
               side_effect=RuntimeError("Token expired")):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 400
    assert "GCal token invalid" in resp.json()["detail"]


def test_scan_502_on_llm_json_error(client, monkeypatch):
    """scan returns 502 if LLM call raises RuntimeError."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials",
               return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call",
               side_effect=RuntimeError("LLM returned invalid JSON")):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 502


def test_scan_502_on_non_dict_llm_response(client, monkeypatch):
    """scan returns 502 if LLM returns a non-dict (e.g., a list)."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials",
               return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call", return_value=["not", "a", "dict"]):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 502


def test_promote_saves_config_only(client, monkeypatch):
    """promote saves config to users.config; ignores any credential fields."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(error=None)

    with patch("api.routes.onboard.supabase", mock_sb):
        resp = client.post(
            "/api/onboard/promote",
            json={"config": {"sleep": {"default_wake_time": "07:00"}}},
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    update_call = mock_sb.from_.return_value.update.call_args
    saved = update_call.args[0]
    assert "config" in saved
    assert "groq_api_key" not in saved
    assert saved["config"]["sleep"]["default_wake_time"] == "07:00"


def test_promote_strips_onboard_draft_key(client, monkeypatch):
    """promote strips _onboard_draft from config before saving."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("api.routes.onboard.supabase", mock_sb):
        resp = client.post(
            "/api/onboard/promote",
            json={"config": {"_onboard_draft": True, "sleep": {"default_wake_time": "07:00"}}},
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    saved = mock_sb.from_.return_value.update.call_args.args[0]["config"]
    assert "_onboard_draft" not in saved
    assert saved["sleep"]["default_wake_time"] == "07:00"


def test_promote_500_on_supabase_error(client, monkeypatch):
    """promote returns 500 if Supabase write raises an exception."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.side_effect = Exception("DB error")

    with patch("api.routes.onboard.supabase", mock_sb):
        resp = client.post(
            "/api/onboard/promote",
            json={"config": {"sleep": {}}},
            headers=_auth_header(),
        )

    assert resp.status_code == 500
    assert "Supabase write failed" in resp.json()["detail"]


# ── new tests for detected_categories ──────────────────────────────────────

def test_scan_returns_detected_categories(client, monkeypatch):
    """scan includes detected_categories in response with color_id resolved."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )
    mock_llm = {
        "proposed_config": {"sleep": {}},
        "detected_categories": [
            {
                "name": "Meetings & calls",
                "color_name": "Flamingo",
                "event_samples": ["standup", "1:1"],
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 15,
            }
        ],
        "questions_for_stage_2": [],
    }
    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call", return_value=mock_llm):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "detected_categories" in data
    cats = data["detected_categories"]
    assert len(cats) == 1
    assert cats[0]["name"] == "Meetings & calls"
    assert cats[0]["color_name"] == "Flamingo"
    assert cats[0]["color_id"] == "4"


def test_scan_unknown_color_name_yields_null_color_id(client, monkeypatch):
    """If LLM outputs an unrecognised color name, color_id is null."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )
    mock_llm = {
        "proposed_config": {"sleep": {}},
        "detected_categories": [
            {
                "name": "Some category",
                "color_name": "NotARealColor",
                "event_samples": [],
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 15,
            }
        ],
        "questions_for_stage_2": [],
    }
    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call", return_value=mock_llm):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    cats = resp.json()["detected_categories"]
    assert cats[0]["color_id"] is None


def test_scan_falls_back_to_defaults_when_no_categories(client, monkeypatch):
    """When LLM returns empty detected_categories, proposed_config.calendar_rules has defaults."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "tok"}}
    )
    mock_llm = {
        "proposed_config": {"sleep": {}},
        "detected_categories": [],
        "questions_for_stage_2": [],
    }
    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._anthropic_json_call", return_value=mock_llm):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )
    assert resp.status_code == 200
    data = resp.json()
    rules = data["proposed_config"]["calendar_rules"]
    assert "Meetings & calls" in rules
    assert "Personal commitments" in rules


def test_translate_color_semantics_maps_ids_to_names():
    """_translate_color_semantics replaces raw IDs with names and filters < 2 count."""
    from api.routes.onboard import _translate_color_semantics
    semantics = {
        "4": {"count": 5, "top_names": ["standup"]},
        "5": {"count": 1, "top_names": ["gym"]},   # filtered out
        "99": {"count": 3, "top_names": ["unknown"]},  # unknown ID kept as-is
    }
    result = _translate_color_semantics(semantics)
    assert "Flamingo" in result
    assert "Banana" not in result
    assert "99" in result
    assert result["Flamingo"]["count"] == 5
