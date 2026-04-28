import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-client-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-client-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

# tests/api/test_todoist_auth.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, follow_redirects=False)

FAKE_TOKEN = "fake-supabase-jwt"
FAKE_USER_ID = "user-def"


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth.verify_token", return_value={"sub": FAKE_USER_ID})
def test_todoist_auth_stores_redirect_after(mock_verify, mock_sb):
    """redirect_after param is stored in users.oauth_redirect_after."""
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get(f"/auth/todoist?token={FAKE_TOKEN}&redirect_after=/dashboard/settings")

    update_kwargs = mock_sb.from_.return_value.update.call_args[0][0]
    assert update_kwargs.get("oauth_redirect_after") == "/dashboard/settings"


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth.verify_token", return_value={"sub": FAKE_USER_ID})
def test_todoist_auth_stores_none_when_omitted(mock_verify, mock_sb):
    """When redirect_after is omitted, NULL is stored."""
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get(f"/auth/todoist?token={FAKE_TOKEN}")

    update_kwargs = mock_sb.from_.return_value.update.call_args[0][0]
    assert update_kwargs.get("oauth_redirect_after") is None


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.todoist_auth.requests.post")
def test_todoist_callback_uses_redirect_after(mock_post, mock_verify_state, mock_sb):
    """Callback redirects to stored oauth_redirect_after."""
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "tok"})
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_redirect_after": "/dashboard/settings"}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    resp = client.get("/auth/todoist/callback?code=abc&state=fake-state")

    assert resp.status_code == 302
    assert "/dashboard/settings" in resp.headers["location"]


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.todoist_auth.requests.post")
def test_todoist_callback_stores_full_token_blob(mock_post, mock_verify_state, mock_sb):
    """Callback persists access_token + refresh_token + expires_at + token_type
    so the background refresh helper has everything it needs."""
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_redirect_after": None}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get("/auth/todoist/callback?code=abc&state=fake-state")

    update_calls = mock_sb.from_.return_value.update.call_args_list
    blobs = [
        call[0][0]["todoist_oauth_token"]
        for call in update_calls
        if "todoist_oauth_token" in call[0][0]
    ]
    assert blobs, "expected at least one update call writing todoist_oauth_token"
    blob = blobs[0]
    assert blob["access_token"] == "fresh-access"
    assert blob["refresh_token"] == "fresh-refresh"
    assert blob["token_type"] == "Bearer"
    assert isinstance(blob["expires_at"], int) and blob["expires_at"] > 0


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.todoist_auth.requests.post")
def test_todoist_callback_handles_legacy_long_lived_response(mock_post, mock_verify_state, mock_sb):
    """Older Todoist apps (and the grandfathered legacy app) omit
    refresh_token + expires_in. We must still persist the access_token
    and leave refresh_token / expires_at as None so the helper treats
    the blob as legacy long-lived."""
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "legacy-tok"},
    )
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_redirect_after": None}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get("/auth/todoist/callback?code=abc&state=fake-state")

    update_calls = mock_sb.from_.return_value.update.call_args_list
    blobs = [
        call[0][0]["todoist_oauth_token"]
        for call in update_calls
        if "todoist_oauth_token" in call[0][0]
    ]
    assert blobs
    blob = blobs[0]
    assert blob["access_token"] == "legacy-tok"
    assert blob["refresh_token"] is None
    assert blob["expires_at"] is None


@patch("api.routes.todoist_auth.supabase")
@patch("api.routes.todoist_auth._verify_state", return_value=FAKE_USER_ID)
@patch("api.routes.todoist_auth.requests.post")
def test_todoist_callback_clears_redirect_after(mock_post, mock_verify_state, mock_sb):
    """Callback clears oauth_redirect_after after use."""
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "tok"})
    mock_sb.from_.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"oauth_redirect_after": "/dashboard/settings"}
    )
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    client.get("/auth/todoist/callback?code=abc&state=fake-state")

    update_calls = mock_sb.from_.return_value.update.call_args_list
    cleared = any(
        call[0][0].get("oauth_redirect_after") is None
        for call in update_calls
    )
    assert cleared
