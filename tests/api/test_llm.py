import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-client-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-client-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import pytest
from unittest.mock import MagicMock


def test_anthropic_json_call_returns_parsed_dict():
    from src.llm import _anthropic_json_call

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"key": "value"}')]
    mock_client.messages.create.return_value = mock_resp

    result = _anthropic_json_call(mock_client, [{"role": "user", "content": "test"}], "test call")
    assert result == {"key": "value"}


def test_anthropic_json_call_retries_once_on_bad_json():
    from src.llm import _anthropic_json_call

    mock_client = MagicMock()
    bad_resp = MagicMock()
    bad_resp.content = [MagicMock(text="not json")]
    good_resp = MagicMock()
    good_resp.content = [MagicMock(text='["a", "b"]')]
    mock_client.messages.create.side_effect = [bad_resp, good_resp]

    result = _anthropic_json_call(mock_client, [{"role": "user", "content": "test"}], "test call")
    assert result == ["a", "b"]
    assert mock_client.messages.create.call_count == 2
