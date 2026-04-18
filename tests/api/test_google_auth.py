# tests/api/test_google_auth.py
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

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, follow_redirects=False)

FAKE_TOKEN = "fake-supabase-jwt"
FAKE_USER_ID = "user-abc"


@patch("api.routes.google_auth.supabase")
@patch("api.routes.google_auth.verify_token", return_value={"sub": FAKE_USER_ID})
@patch("api.routes.google_auth.Flow")
def test_google_auth_stores_redirect_after(mock_flow_cls, mock_verify, mock_sb):
    """redirect_after query param is written to users.oauth_redirect_after."""
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth", None)
    mock_flow.code_verifier = "verifier-123"
    mock_flow_cls.from_client_config.return_value = mock_flow
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get(f"/auth/google?token={FAKE_TOKEN}&redirect_after=/dashboard/settings")

    update_call_kwargs = mock_sb.from_.return_value.update.call_args[0][0]
    assert update_call_kwargs.get("oauth_redirect_after") == "/dashboard/settings"


@patch("api.routes.google_auth.supabase")
@patch("api.routes.google_auth.verify_token", return_value={"sub": FAKE_USER_ID})
@patch("api.routes.google_auth.Flow")
def test_google_auth_no_redirect_after_defaults_to_none(mock_flow_cls, mock_verify, mock_sb):
    """When redirect_after is omitted, nothing is written for it (stays NULL)."""
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth", None)
    mock_flow.code_verifier = "verifier-xyz"
    mock_flow_cls.from_client_config.return_value = mock_flow
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get(f"/auth/google?token={FAKE_TOKEN}")

    update_call_kwargs = mock_sb.from_.return_value.update.call_args[0][0]
    assert update_call_kwargs.get("oauth_redirect_after") is None


@patch("api.routes.google_auth.supabase")
@patch("api.routes.google_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.google_auth.Flow")
def test_google_callback_uses_redirect_after(mock_flow_cls, mock_verify_state, mock_sb):
    """Callback redirects to stored oauth_redirect_after URL."""
    mock_flow = MagicMock()
    mock_flow.credentials.to_json.return_value = "{}"
    mock_flow_cls.from_client_config.return_value = mock_flow
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_code_verifier": "v", "oauth_redirect_after": "/dashboard/settings"}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(error=None)

    resp = client.get("/auth/google/callback?code=abc&state=fake-state")

    assert resp.status_code == 302
    assert "/dashboard/settings" in resp.headers["location"]


@patch("api.routes.google_auth.supabase")
@patch("api.routes.google_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.google_auth.Flow")
def test_google_callback_clears_redirect_after(mock_flow_cls, mock_verify_state, mock_sb):
    """Callback clears oauth_redirect_after after using it."""
    mock_flow = MagicMock()
    mock_flow.credentials.to_json.return_value = "{}"
    mock_flow_cls.from_client_config.return_value = mock_flow
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_code_verifier": "v", "oauth_redirect_after": "/dashboard/settings"}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get("/auth/google/callback?code=abc&state=fake-state")

    # Second update call clears the verifier and redirect_after
    update_calls = mock_sb.from_.return_value.update.call_args_list
    cleared = any(
        call[0][0].get("oauth_redirect_after") is None
        for call in update_calls
    )
    assert cleared
