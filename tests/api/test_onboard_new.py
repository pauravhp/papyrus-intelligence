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
