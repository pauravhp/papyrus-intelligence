import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock, patch
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest


@pytest.fixture
def user_ctx():
    return {
        "user_id": "uid-123",
        "config": {
            "user": {"timezone": "America/Vancouver"},
            "calendar_ids": [],
            "sleep": {"default_wake_time": "07:00"},
            "rules": {"hard": [], "soft": []},
        },
        "anthropic_api_key": "sk-ant-test",
        "todoist_api_key": "tod_test",
        "gcal_service": MagicMock(),
        "supabase": MagicMock(),
    }


def test_execute_get_tasks_returns_list(user_ctx):
    from api.services.agent_tools import execute_get_tasks
    mock_client = MagicMock()
    mock_client.get_tasks.return_value = []
    with patch("api.services.agent_tools.TodoistClient", return_value=mock_client):
        result = execute_get_tasks("today", user_ctx)
    assert isinstance(result, list)
    mock_client.get_tasks.assert_called_once_with("today")


def test_execute_get_calendar_returns_list(user_ctx):
    from api.services.agent_tools import execute_get_calendar
    with patch("api.services.agent_tools.get_events", return_value=[]):
        result = execute_get_calendar(date.today().isoformat(), user_ctx)
    assert isinstance(result, list)


def test_execute_push_task_clears_due_and_comments(user_ctx):
    from api.services.agent_tools import execute_push_task
    mock_client = MagicMock()
    with patch("api.services.agent_tools.TodoistClient", return_value=mock_client):
        execute_push_task("task-123", "deadline slipped", user_ctx)
    mock_client.clear_task_due.assert_called_once_with("task-123")
    mock_client.add_comment.assert_called_once()


def test_execute_get_status_queries_schedule_log(user_ctx):
    from api.services.agent_tools import execute_get_status
    sb = user_ctx["supabase"]
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    result = execute_get_status(user_ctx)
    assert result == {"status": "no_confirmed_schedule", "schedule": None}


def test_execute_confirm_schedule_calls_gcal_and_todoist(user_ctx):
    from api.services.agent_tools import execute_confirm_schedule
    schedule = {
        "scheduled": [
            {
                "task_id": "t1",
                "task_name": "Deep Work",
                "start_time": "2026-04-12T09:00:00-07:00",
                "end_time": "2026-04-12T10:30:00-07:00",
                "duration_minutes": 90,
            }
        ],
        "pushed": [],
        "reasoning_summary": "All scheduled.",
    }
    svc = user_ctx["gcal_service"]
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "gcal-001"}
    mock_todoist = MagicMock()
    with patch("api.services.agent_tools.TodoistClient", return_value=mock_todoist), \
         patch("api.services.agent_tools.create_event", return_value="gcal-001"):
        result = execute_confirm_schedule(schedule, user_ctx)
    assert result["confirmed"] is True
    assert result["gcal_events_created"] == 1


def test_all_tool_schemas_are_valid():
    from api.services.agent_tools import TOOL_SCHEMAS
    assert len(TOOL_SCHEMAS) == 9  # removed log_project_session; onboard tools in /api/onboard/* HTTP routes
    for schema in TOOL_SCHEMAS:
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"


def test_tool_schemas_include_rhythm_tools():
    from api.services.agent_tools import TOOL_SCHEMAS
    names = [s["name"] for s in TOOL_SCHEMAS]
    assert "get_rhythms" in names
    assert "manage_rhythm" in names
    assert "log_project_session" not in names
    assert "get_projects" not in names


def test_schedule_day_injects_project_as_synthetic_task():
    """Projects with remaining hours appear in schedule_day input as proj_<id> tasks."""
    from api.services.agent_tools import execute_schedule_day
    from unittest.mock import MagicMock, patch

    ctx = {
        "config": {
            "user": {"timezone": "America/Vancouver"},
            "calendar_ids": [],
            "sleep": {},
            "rules": {"hard": [], "soft": []},
        },
        "todoist_api_key": "tok",
        "anthropic_api_key": "sk-ant",
        "groq_api_key": None,
        "gcal_service": MagicMock(),
        "user_id": "u1",
        "supabase": MagicMock(),
    }

    rhythm_row = {
        "id": 7, "rhythm_name": "App Side Project",
        "sessions_per_week": 2, "session_min_minutes": 90, "session_max_minutes": 180,
        "end_date": None, "sort_order": 0, "created_at": "x", "updated_at": "x",
    }

    captured_tasks = []

    def fake_schedule_day(tasks, free_windows, config, context_note, **kwargs):
        captured_tasks.extend(tasks)
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    with patch("api.services.agent_tools.TodoistClient") as MockTodoist, \
         patch("api.services.agent_tools.get_events", return_value=[]), \
         patch("api.services.agent_tools.compute_free_windows", return_value=[]), \
         patch("api.services.agent_tools.schedule_day", side_effect=fake_schedule_day), \
         patch("api.services.agent_tools.get_active_rhythms", return_value=[rhythm_row]):
        MockTodoist.return_value.get_tasks.return_value = []
        MockTodoist.return_value.get_todays_scheduled_tasks.return_value = []
        execute_schedule_day("", "2026-04-13", ctx)

    proj_tasks = [t for t in captured_tasks if t.id == "proj_7"]
    assert len(proj_tasks) == 1
    assert proj_tasks[0].content == "App Side Project"
    assert proj_tasks[0].is_rhythm is True
    assert proj_tasks[0].session_max_minutes == 180
    assert proj_tasks[0].duration_minutes == 90  # session_min
    assert proj_tasks[0].sessions_per_week == 2


def test_schedule_day_passes_scheduled_tasks_as_keyword_arg():
    """Bug fix: scheduled_tasks must be passed as a keyword arg to compute_free_windows.
    The 4th positional param is late_night_prior:bool, not scheduled_tasks.
    Passing a list positionally caused a spurious 90-min wake penalty and
    failed to block already-scheduled task slots."""
    from api.services.agent_tools import execute_schedule_day
    from src.models import TodoistTask

    TZ = ZoneInfo("America/Vancouver")
    ctx = {
        "config": {
            "user": {"timezone": "America/Vancouver"},
            "calendar_ids": [],
            "sleep": {},
            "rules": {"hard": [], "soft": []},
        },
        "todoist_api_key": "tok",
        "anthropic_api_key": "sk-ant",
        "gcal_service": MagicMock(),
        "user_id": "u1",
        "supabase": MagicMock(),
    }

    pre_scheduled = [
        TodoistTask(
            id="t-pre", content="Existing Task", project_id="p1", priority=1,
            due_datetime=datetime(2026, 4, 15, 10, 0, tzinfo=TZ),
            deadline=None, duration_minutes=60, labels=[], is_inbox=False,
        )
    ]
    captured = {}

    def fake_compute_free_windows(events, target_date, context, late_night_prior=False, scheduled_tasks=None, **kw):
        captured["late_night_prior"] = late_night_prior
        captured["scheduled_tasks"] = scheduled_tasks
        return []

    with patch("api.services.agent_tools.TodoistClient") as MockTodoist, \
         patch("api.services.agent_tools.get_events", return_value=[]), \
         patch("api.services.agent_tools.compute_free_windows", side_effect=fake_compute_free_windows), \
         patch("api.services.agent_tools.schedule_day", return_value={"scheduled": [], "pushed": [], "reasoning_summary": ""}), \
         patch("api.services.agent_tools.get_active_rhythms", return_value=[]):
        MockTodoist.return_value.get_tasks.return_value = []
        MockTodoist.return_value.get_todays_scheduled_tasks.return_value = pre_scheduled
        execute_schedule_day("", "2026-04-15", ctx)

    assert captured.get("late_night_prior") is False, (
        "scheduled_tasks list was passed as late_night_prior — use keyword arg"
    )
    assert captured.get("scheduled_tasks") == pre_scheduled, (
        "scheduled_tasks was not forwarded to compute_free_windows"
    )


def test_schedule_day_pushes_llm_times_outside_free_windows():
    """LLM-proposed start/end times that fall outside computed free windows are
    moved to pushed — prevents scheduling tasks on top of GCal events."""
    from api.services.agent_tools import execute_schedule_day
    from src.models import FreeWindow

    TZ = ZoneInfo("America/Vancouver")
    ctx = {
        "config": {
            "user": {"timezone": "America/Vancouver"},
            "calendar_ids": [],
            "sleep": {},
            "rules": {"hard": [], "soft": []},
        },
        "todoist_api_key": "tok",
        "anthropic_api_key": "sk-ant",
        "gcal_service": MagicMock(),
        "user_id": "u1",
        "supabase": MagicMock(),
    }

    # Only one free window: 10:00–11:00
    free_window = FreeWindow(
        start=datetime(2026, 4, 15, 10, 0, tzinfo=TZ),
        end=datetime(2026, 4, 15, 11, 0, tzinfo=TZ),
        duration_minutes=60,
        block_type="morning",
    )

    # LLM proposes 14:00–15:00 — this slot is blocked by a GCal event (not in free windows)
    llm_result = {
        "scheduled": [
            {
                "task_id": "t1",
                "task_name": "Task A",
                "start_time": "2026-04-15T14:00:00-07:00",
                "end_time": "2026-04-15T15:00:00-07:00",
                "duration_minutes": 60,
            }
        ],
        "pushed": [],
        "reasoning_summary": "scheduled",
    }

    with patch("api.services.agent_tools.TodoistClient") as MockTodoist, \
         patch("api.services.agent_tools.get_events", return_value=[]), \
         patch("api.services.agent_tools.compute_free_windows", return_value=[free_window]), \
         patch("api.services.agent_tools.schedule_day", return_value=llm_result), \
         patch("api.services.agent_tools.get_active_rhythms", return_value=[]):
        MockTodoist.return_value.get_tasks.return_value = []
        MockTodoist.return_value.get_todays_scheduled_tasks.return_value = []
        result = execute_schedule_day("", "2026-04-15", ctx)

    assert len(result["scheduled"]) == 0, "Task outside free window must not appear in scheduled"
    assert len(result["pushed"]) == 1, "Task outside free window must be moved to pushed"
    assert result["pushed"][0]["task_id"] == "t1"


def test_confirm_schedule_skips_todoist_for_project_tasks():
    """Items with task_id starting with proj_ get a GCal event but no Todoist write."""
    from api.services.agent_tools import execute_confirm_schedule
    from unittest.mock import MagicMock, patch

    gcal_svc = MagicMock()
    sb = MagicMock()
    sb.from_.return_value.insert.return_value.execute.return_value.data = []

    ctx = {
        "config": {"user": {"timezone": "America/Vancouver"}, "rules": {}},
        "todoist_api_key": "tok",
        "gcal_service": gcal_svc,
        "user_id": "u1",
        "supabase": sb,
    }

    schedule = {
        "scheduled": [
            {
                "task_id": "proj_7",
                "task_name": "App Side Project",
                "start_time": "2026-04-13T10:30:00-07:00",
                "end_time": "2026-04-13T12:30:00-07:00",
                "duration_minutes": 120,
            }
        ],
        "pushed": [],
    }

    with patch("api.services.agent_tools.TodoistClient") as MockTodoist, \
         patch("api.services.agent_tools.create_event", return_value="gcal-id-1"):
        result = execute_confirm_schedule(schedule, ctx)
        # GCal event should be created
        assert result["gcal_events_created"] == 1
        # Todoist should NOT be called for proj_ task
        MockTodoist.return_value.schedule_task.assert_not_called()


def test_execute_get_calendar_uses_source_calendar_ids(user_ctx):
    """execute_get_calendar prefers source_calendar_ids over calendar_ids."""
    user_ctx["config"]["source_calendar_ids"] = ["primary", "work@co.com"]
    user_ctx["config"]["calendar_ids"] = ["old@co.com"]

    with patch("api.services.agent_tools.get_events", return_value=[]) as mock_get:
        from api.services.agent_tools import execute_get_calendar
        execute_get_calendar(date.today().isoformat(), user_ctx)

    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["calendar_ids"] == ["primary", "work@co.com"]


def test_execute_get_calendar_falls_back_to_primary(user_ctx):
    """execute_get_calendar falls back to ['primary'] when no calendar config set."""
    user_ctx["config"].pop("source_calendar_ids", None)
    user_ctx["config"].pop("calendar_ids", None)

    with patch("api.services.agent_tools.get_events", return_value=[]) as mock_get:
        from api.services.agent_tools import execute_get_calendar
        execute_get_calendar(date.today().isoformat(), user_ctx)

    _, kwargs = mock_get.call_args
    assert kwargs["calendar_ids"] == ["primary"]


def test_execute_confirm_schedule_uses_write_calendar_id(user_ctx):
    """confirm_schedule passes write_calendar_id to create_event and stores it in schedule_log."""
    user_ctx["config"]["write_calendar_id"] = "work@co.com"
    schedule = {
        "scheduled": [{
            "task_id": "t1",
            "task_name": "Deep Work",
            "start_time": "2026-04-16T09:00:00-07:00",
            "end_time": "2026-04-16T10:30:00-07:00",
            "duration_minutes": 90,
        }],
        "pushed": [],
        "reasoning_summary": "Scheduled.",
    }
    sb = user_ctx["supabase"]
    sb.from_.return_value.insert.return_value.execute.return_value = MagicMock()

    with patch("api.services.agent_tools.create_event", return_value="evt-1") as mock_create, \
         patch("api.services.agent_tools.TodoistClient") as MockTD:
        MockTD.return_value.schedule_task.return_value = None
        from api.services.agent_tools import execute_confirm_schedule
        execute_confirm_schedule(schedule, user_ctx)

    # create_event must be called with the configured calendar
    _, kwargs = mock_create.call_args
    assert kwargs.get("calendar_id") == "work@co.com"

    # schedule_log insert must include gcal_write_calendar_id
    insert_call = sb.from_.return_value.insert.call_args
    inserted_data = insert_call.args[0]
    assert inserted_data["gcal_write_calendar_id"] == "work@co.com"
