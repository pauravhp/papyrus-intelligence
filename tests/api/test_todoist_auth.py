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
    return TestClient(app, follow_redirects=False)


def test_todoist_oauth_start_redirects_to_todoist(client):
    """GET /auth/todoist?token=... redirects to Todoist consent URL."""
    mock_user = {"sub": "user-123"}
    with patch("api.routes.todoist_auth.verify_token", return_value=mock_user), \
         patch("api.routes.todoist_auth.supabase"):
        resp = client.get("/auth/todoist?token=fake-jwt")

    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "api.todoist.com/oauth/authorize" in location
    assert "data%3Aread_write" in location or "data:read_write" in location
    assert "test-todoist-client-id" in location


def test_todoist_oauth_callback_stores_token(client):
    """GET /auth/todoist/callback stores access token in Supabase and redirects."""
    import hmac, hashlib, time
    from api.config import settings

    user_id = "user-abc"
    timestamp = str(int(time.time()))
    payload = f"{user_id}:{timestamp}"
    sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    state = f"{payload}:{sig}"

    mock_sb = MagicMock()
    mock_sb.from_.return_value.update.return_value.eq.return_value.execute.return_value.data = {}

    with patch("api.routes.todoist_auth.supabase", mock_sb), \
         patch("api.routes.todoist_auth.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "tok_abc123", "token_type": "Bearer"}
        resp = client.get(f"/auth/todoist/callback?code=authcode&state={state}")

    assert resp.status_code == 302
    assert "onboard" in resp.headers["location"]
    # Verify Supabase was called with the token
    update_call = mock_sb.from_.return_value.update.call_args
    stored = update_call[0][0]
    assert stored["todoist_oauth_token"]["access_token"] == "tok_abc123"


def test_todoist_oauth_callback_rejects_expired_state(client):
    """Expired state returns 400."""
    import hmac, hashlib
    from api.config import settings

    user_id = "user-abc"
    old_timestamp = str(1000000)  # way in the past
    payload = f"{user_id}:{old_timestamp}"
    sig = hmac.new(
        settings.ENCRYPTION_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    state = f"{payload}:{sig}"

    resp = client.get(f"/auth/todoist/callback?code=authcode&state={state}")
    assert resp.status_code == 400
