import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from src.models import FreeWindow, TodoistTask


def _make_tasks():
    tz = ZoneInfo("America/Vancouver")
    return [
        TodoistTask(
            id="t1", content="Write report", project_id="p1",
            priority=3, due_datetime=None, deadline=None,
            duration_minutes=90, labels=[], is_inbox=True,
        )
    ]


def _make_windows():
    tz = ZoneInfo("America/Vancouver")
    return [
        FreeWindow(
            start=datetime(2026, 4, 12, 9, 0, tzinfo=tz),
            end=datetime(2026, 4, 12, 10, 30, tzinfo=tz),
            duration_minutes=90,
            block_type="morning",
        )
    ]


def _make_config():
    return {"user": {"timezone": "America/Vancouver"}, "sleep": {}, "rules": {"hard": [], "soft": []}}


def test_schedule_day_returns_structured_output():
    """schedule_day returns scheduled list + pushed list + reasoning_summary."""
    from api.services.schedule_service import schedule_day

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text='{"scheduled":[{"task_id":"t1","task_name":"Write report","start_time":"2026-04-12T09:00:00-07:00","end_time":"2026-04-12T10:30:00-07:00","duration_minutes":90}],"pushed":[],"reasoning_summary":"All scheduled."}')]

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = schedule_day(
            tasks=_make_tasks(),
            free_windows=_make_windows(),
            config=_make_config(),
            context_note="normal day",
            anthropic_api_key="sk-ant-test",
            target_date="2026-04-12",
        )

    assert "scheduled" in result
    assert len(result["scheduled"]) == 1
    assert result["scheduled"][0]["task_id"] == "t1"
    assert "pushed" in result
    assert "reasoning_summary" in result


def test_schedule_day_retries_on_invalid_json():
    """schedule_day retries once on JSON parse failure, raises RuntimeError on second."""
    from api.services.schedule_service import schedule_day

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="not json at all")]

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        with pytest.raises(RuntimeError, match="invalid JSON"):
            schedule_day(
                tasks=_make_tasks(),
                free_windows=_make_windows(),
                config=_make_config(),
                context_note="",
                anthropic_api_key="sk-ant-test",
                target_date="2026-04-12",
            )


def test_build_prompt_shows_session_range_for_budget_task():
    from src.models import TodoistTask, FreeWindow
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from api.services.schedule_service import _build_prompt

    tz = ZoneInfo("America/Vancouver")
    task = TodoistTask(
        id="proj_1",
        content="App Side Project",
        project_id="none",
        priority=3,
        due_datetime=None,
        deadline=None,
        duration_minutes=90,
        labels=[],
        is_inbox=False,
        is_rhythm=True,
        session_max_minutes=180,
        sessions_per_week=2,
    )
    window = FreeWindow(
        start=datetime(2026, 4, 13, 9, 0, tzinfo=tz),
        end=datetime(2026, 4, 13, 12, 0, tzinfo=tz),
        duration_minutes=180,
        block_type="morning",
    )
    prompt = _build_prompt([task], [window], {}, "", "2026-04-13")
    assert "90-180min" in prompt
    assert "[2x/week]" in prompt
    assert "proj_1" in prompt
