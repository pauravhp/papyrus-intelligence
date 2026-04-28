"""
Unit tests for api.services.todoist_token.get_valid_todoist_token.

Covers all paths the helper must handle:
  - fresh access_token (no refresh)
  - near-expiry refresh + rotation
  - already-expired refresh + rotation
  - legacy long-lived blob (no expires_at) returned as-is
  - 400 from Todoist on refresh
  - expired but no refresh_token stored
  - network error during refresh
"""

import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from api.services.todoist_token import get_valid_todoist_token, TodoistTokenError


def _mock_supabase_with_blob(blob):
    """Return a MagicMock supabase whose users SELECT returns the given blob."""
    sb = MagicMock()
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = {"todoist_oauth_token": blob}
    return sb


def test_get_valid_token_returns_access_token_when_fresh():
    """Token expires 30 min from now → return as-is, no refresh request."""
    blob = {
        "access_token": "fresh-access",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) + 30 * 60,
        "token_type": "Bearer",
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        result = get_valid_todoist_token(sb, "user-1")

    assert result == "fresh-access"
    mock_post.assert_not_called()
    sb.from_.return_value.update.assert_not_called()


def test_get_valid_token_refreshes_when_near_expiry():
    """Token expires inside the 5-min refresh window → rotate."""
    blob = {
        "access_token": "old-access",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) + 60,  # 1 min from now → inside 5-min window
        "token_type": "Bearer",
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "access_token": "new-access",
                "refresh_token": "rt-2",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        result = get_valid_todoist_token(sb, "user-1")

    assert result == "new-access"
    mock_post.assert_called_once()
    update_arg = sb.from_.return_value.update.call_args[0][0]
    new_blob = update_arg["todoist_oauth_token"]
    assert new_blob["access_token"] == "new-access"
    assert new_blob["refresh_token"] == "rt-2"
    assert new_blob["expires_at"] >= int(time.time()) + 3500


def test_get_valid_token_refreshes_when_already_expired():
    """Token already past expiry → rotate."""
    blob = {
        "access_token": "stale",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) - 1000,
        "token_type": "Bearer",
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "access_token": "new-access",
                "refresh_token": "rt-2",
                "expires_in": 3600,
            },
        )
        result = get_valid_todoist_token(sb, "user-1")

    assert result == "new-access"
    mock_post.assert_called_once()
    update_arg = sb.from_.return_value.update.call_args[0][0]
    assert update_arg["todoist_oauth_token"]["refresh_token"] == "rt-2"


def test_get_valid_token_handles_legacy_blob_no_expires_at():
    """Legacy long-lived shape ({access_token: ...}) returned as-is."""
    blob = {"access_token": "legacy-long-lived"}
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        result = get_valid_todoist_token(sb, "user-1")

    assert result == "legacy-long-lived"
    mock_post.assert_not_called()
    sb.from_.return_value.update.assert_not_called()


def test_get_valid_token_raises_when_refresh_rejected_400():
    """Todoist returns 400 → TodoistTokenError, no DB write."""
    blob = {
        "access_token": "stale",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) - 10,
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="invalid_grant")
        with pytest.raises(TodoistTokenError):
            get_valid_todoist_token(sb, "user-1")

    sb.from_.return_value.update.assert_not_called()


def test_get_valid_token_raises_when_no_refresh_token_and_expired():
    """Expired token but no refresh_token → reconnect required."""
    blob = {
        "access_token": "stale",
        "expires_at": int(time.time()) - 10,
        # no refresh_token
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        with pytest.raises(TodoistTokenError):
            get_valid_todoist_token(sb, "user-1")

    mock_post.assert_not_called()


def test_get_valid_token_handles_network_error():
    """requests.post raises → TodoistTokenError."""
    blob = {
        "access_token": "stale",
        "refresh_token": "rt-1",
        "expires_at": int(time.time()) - 10,
    }
    sb = _mock_supabase_with_blob(blob)

    with patch("api.services.todoist_token.requests.post") as mock_post:
        mock_post.side_effect = requests.ConnectionError("boom")
        with pytest.raises(TodoistTokenError):
            get_valid_todoist_token(sb, "user-1")

    sb.from_.return_value.update.assert_not_called()


def test_get_valid_token_raises_when_no_token_stored():
    """User row has no todoist_oauth_token → TodoistTokenError."""
    sb = MagicMock()
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = {"todoist_oauth_token": None}

    with pytest.raises(TodoistTokenError):
        get_valid_todoist_token(sb, "user-1")
