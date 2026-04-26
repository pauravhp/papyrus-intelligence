import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import patch, call


def test_capture_calls_posthog_with_correct_args():
    with patch("api.services.analytics.posthog.capture") as mock_capture:
        from api.services.analytics import capture
        capture("user-123", "schedule_confirmed", {"task_count": 3})
        mock_capture.assert_called_once_with(
            distinct_id="user-123",
            event="schedule_confirmed",
            properties={"task_count": 3},
        )


def test_capture_uses_empty_dict_when_properties_omitted():
    with patch("api.services.analytics.posthog.capture") as mock_capture:
        from api.services.analytics import capture
        capture("user-123", "rhythm_created")
        mock_capture.assert_called_once_with(
            distinct_id="user-123",
            event="rhythm_created",
            properties={},
        )


def test_capture_swallows_exceptions_silently():
    with patch("api.services.analytics.posthog.capture", side_effect=Exception("PostHog unavailable")):
        from api.services.analytics import capture
        # Must not raise
        capture("user-123", "schedule_confirmed", {})
