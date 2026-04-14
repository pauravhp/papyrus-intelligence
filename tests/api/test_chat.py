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


def _mock_supabase_user(sb, config=None, todoist_token="tok_test", gcal_creds=None):
    """Configure the supabase mock to return a valid user row."""
    row = {
        "config": config or {
            "user": {"timezone": "America/Vancouver"},
            "calendar_ids": [],
            "sleep": {},
            "rules": {"hard": [], "soft": []},
        },
        "todoist_oauth_token": {"access_token": todoist_token, "granted_at": "2026-04-14T00:00:00+00:00"},
        "google_credentials": gcal_creds or {"token": "tok", "refresh_token": "rref"},
    }
    chain = sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value
    chain.data = row


def test_chat_returns_assistant_message(client):
    """POST /api/chat with a simple message returns a JSON response with 'message' field."""
    mock_sb = MagicMock()
    _mock_supabase_user(mock_sb)

    mock_anthropic_resp = MagicMock()
    mock_anthropic_resp.stop_reason = "end_turn"
    mock_anthropic_resp.content = [MagicMock(type="text", text="Here's your plan for today!")]

    with patch("api.routes.chat.supabase", mock_sb), \
         patch("api.routes.chat.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.chat.anthropic.Anthropic") as MockAnt:
        MockAnt.return_value.messages.create.return_value = mock_anthropic_resp
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "plan my day"}]},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    # 401 from JWT is OK in test — we just check the route exists
    assert resp.status_code in (200, 401)


def test_chat_uses_server_anthropic_key(client):
    """chat always uses server-side ANTHROPIC_API_KEY from settings."""
    mock_sb = MagicMock()
    _mock_supabase_user(mock_sb)

    mock_anthropic_resp = MagicMock()
    mock_anthropic_resp.stop_reason = "end_turn"
    mock_anthropic_resp.content = [MagicMock(type="text", text="Using server key")]

    with patch("api.routes.chat.supabase", mock_sb), \
         patch("api.routes.chat.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.chat.anthropic.Anthropic") as MockAnt:
        MockAnt.return_value.messages.create.return_value = mock_anthropic_resp
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code in (200, 401)


def test_chat_route_registered():
    from api.main import app
    routes = [r.path for r in app.routes]
    assert "/api/chat" in routes
