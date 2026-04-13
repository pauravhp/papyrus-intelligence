# tests/api/test_onboard_new.py
from unittest.mock import MagicMock, patch, call
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


def test_save_credentials_stores_encrypted_keys(client, monkeypatch):
    """save-credentials encrypts each non-empty key and writes to Supabase."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.rpc.return_value.execute.return_value.data = "encrypted_value"
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.set_encryption_key") as mock_enc:
        resp = client.post(
            "/api/onboard/save-credentials",
            json={
                "groq_api_key": "gsk_test",
                "anthropic_api_key": "",
                "todoist_api_key": "tod_test",
            },
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    mock_enc.assert_called_once()
    # encrypt_field RPC called twice (groq + todoist; anthropic empty so skipped)
    encrypt_calls = [c for c in mock_sb.rpc.call_args_list if c.args[0] == "encrypt_field"]
    assert len(encrypt_calls) == 2
    mock_sb.from_.return_value.update.assert_called_once()


def test_save_credentials_skips_empty_keys(client, monkeypatch):
    """Empty string keys are not encrypted or written."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.rpc.return_value.execute.return_value.data = "enc"
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(error=None)

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.set_encryption_key"):
        resp = client.post(
            "/api/onboard/save-credentials",
            json={"groq_api_key": "", "anthropic_api_key": "", "todoist_api_key": ""},
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    encrypt_calls = [c for c in mock_sb.rpc.call_args_list if c.args[0] == "encrypt_field"]
    assert len(encrypt_calls) == 0
    mock_sb.from_.return_value.update.assert_not_called()


def test_scan_returns_proposed_config(client, monkeypatch):
    """scan reads credentials from Supabase and returns proposed_config."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={
            "google_credentials": {"token": "tok", "refresh_token": "rref",
                                   "token_uri": "https://oauth2.googleapis.com/token",
                                   "client_id": "cid", "client_secret": "cs",
                                   "scopes": ["https://www.googleapis.com/auth/calendar.events"]},
            "groq_api_key": "enc_groq",
            "anthropic_api_key": None,
        }
    )
    mock_sb.rpc.return_value.execute.return_value.data = "gsk_decrypted"

    mock_proposed = {"sleep": {"default_wake_time": "07:00"}, "calendar_rules": {}}

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.set_encryption_key"), \
         patch("api.routes.onboard.build_gcal_service_from_credentials",
               return_value=(MagicMock(), None)), \
         patch("api.routes.onboard.get_events", return_value=[]), \
         patch("api.routes.onboard.build_pattern_summary", return_value={}), \
         patch("api.routes.onboard.build_onboard_prompt", return_value=[]), \
         patch("api.routes.onboard._groq_json_call",
               return_value={"proposed_config": mock_proposed, "questions_for_stage_2": []}):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "proposed_config" in data
    assert "questions" in data


def test_scan_raises_400_if_no_gcal_creds(client, monkeypatch):
    """scan returns 400 if google_credentials not set for the user."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": None, "groq_api_key": "enc_groq", "anthropic_api_key": None}
    )

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.set_encryption_key"):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 400


def test_scan_raises_400_if_no_llm_key(client, monkeypatch):
    """scan returns 400 if neither groq nor anthropic key is stored."""
    _mock_verify(monkeypatch)
    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"google_credentials": {"token": "t"}, "groq_api_key": None, "anthropic_api_key": None}
    )
    mock_sb.rpc.return_value.execute.return_value.data = None

    with patch("api.routes.onboard.supabase", mock_sb), \
         patch("api.routes.onboard.set_encryption_key"):
        resp = client.post(
            "/api/onboard/scan",
            json={"timezone": "America/Vancouver", "calendar_ids": []},
            headers=_auth_header(),
        )

    assert resp.status_code == 400
