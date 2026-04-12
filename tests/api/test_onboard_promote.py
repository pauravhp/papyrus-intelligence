import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_supabase():
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value = MagicMock(data="encrypted_value")
    sb.from_.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{}], error=None)
    return sb


def test_promote_saves_api_keys(mock_supabase):
    """Promote endpoint must call set_encryption_key then save groq/anthropic/todoist keys."""
    from api.routes.onboard import onboard_promote, PromoteRequest
    req = PromoteRequest(
        draft_config={"sleep": {"default_wake_time": "07:00"}},
        groq_api_key="gsk_test",
        anthropic_api_key="sk-ant-test",
        todoist_api_key="tod_test",
    )
    with patch("api.routes.onboard.supabase", mock_supabase), \
         patch("api.routes.onboard.set_encryption_key") as mock_enc:
        result = onboard_promote(req, user={"sub": "user-uuid-123"})

    mock_enc.assert_called_once()
    # Verify keys were saved (second update call)
    calls = mock_supabase.from_.return_value.update.call_args_list
    key_call_args = [str(c) for c in calls]
    assert any("groq_api_key" in a for a in key_call_args)
    assert result.success is True
