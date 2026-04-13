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
        "groq_api_key": "gsk_test",
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
    assert len(TOOL_SCHEMAS) == 10  # 6 scheduling tools + get_date; onboard tools in /api/onboard/* HTTP routes
    for schema in TOOL_SCHEMAS:
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"


def test_execute_get_projects_returns_list():
    from api.services.agent_tools import execute_get_projects
    sb = MagicMock()
    sb.from_.return_value.select.return_value.eq.return_value.gt.return_value.order.return_value.execute.return_value.data = [
        {
            "id": 1, "project_name": "App Project", "total_budget_hours": 22.0,
            "remaining_hours": 20.0, "session_min_minutes": 90, "session_max_minutes": 180,
            "deadline": None, "priority": 3, "created_at": "x", "updated_at": "x",
        }
    ]
    ctx = {"user_id": "u1", "supabase": sb}
    result = execute_get_projects({}, ctx)
    assert isinstance(result, list)
    assert result[0]["project_name"] == "App Project"
    assert "deadline_pressure" in result[0]


def test_execute_log_project_session_decrements():
    from api.services.agent_tools import execute_log_project_session
    sb = MagicMock()
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "remaining_hours": 20.0
    }
    sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.select.return_value.single.return_value.execute.return_value.data = {
        "id": 1, "project_name": "App", "total_budget_hours": 22.0,
        "remaining_hours": 18.5, "session_min_minutes": 90, "session_max_minutes": 180,
        "deadline": None, "priority": 3, "created_at": "x", "updated_at": "x",
    }
    ctx = {"user_id": "u1", "supabase": sb}
    result = execute_log_project_session({"project_id": 1, "hours_worked": 1.5}, ctx)
    assert result["remaining_hours"] == 18.5


def test_execute_manage_project_create():
    from api.services.agent_tools import execute_manage_project
    sb = MagicMock()
    sb.from_.return_value.insert.return_value.execute.return_value.data = [
        {
            "id": 2, "project_name": "GPU Study", "total_budget_hours": 10.0,
            "remaining_hours": 10.0, "session_min_minutes": 45, "session_max_minutes": 60,
            "deadline": None, "priority": 3, "created_at": "x", "updated_at": "x",
        }
    ]
    ctx = {"user_id": "u1", "supabase": sb}
    result = execute_manage_project({
        "action": "create",
        "name": "GPU Study",
        "total_hours": 10.0,
        "session_min": 45,
        "session_max": 60,
    }, ctx)
    assert result["project_name"] == "GPU Study"


def test_tool_schemas_include_project_tools():
    from api.services.agent_tools import TOOL_SCHEMAS
    names = [s["name"] for s in TOOL_SCHEMAS]
    assert "get_projects" in names
    assert "manage_project" in names
    assert "log_project_session" in names
    assert len(TOOL_SCHEMAS) == 10  # 7 existing + 3 new


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

    project_row = {
        "id": 7, "project_name": "App Side Project", "total_budget_hours": 22.0,
        "remaining_hours": 20.0, "session_min_minutes": 90, "session_max_minutes": 180,
        "deadline": "2026-05-01", "priority": 3, "created_at": "x", "updated_at": "x",
    }

    captured_tasks = []

    def fake_schedule_day(tasks, free_windows, config, context_note, **kwargs):
        captured_tasks.extend(tasks)
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    with patch("api.services.agent_tools.TodoistClient") as MockTodoist, \
         patch("api.services.agent_tools.get_events", return_value=[]), \
         patch("api.services.agent_tools.compute_free_windows", return_value=[]), \
         patch("api.services.agent_tools.schedule_day", side_effect=fake_schedule_day), \
         patch("api.services.agent_tools.get_active_projects", return_value=[{**project_row, "deadline_pressure": "at_risk"}]):
        MockTodoist.return_value.get_tasks.return_value = []
        MockTodoist.return_value.get_todays_scheduled_tasks.return_value = []
        execute_schedule_day("", "2026-04-13", ctx)

    proj_tasks = [t for t in captured_tasks if t.id == "proj_7"]
    assert len(proj_tasks) == 1
    assert proj_tasks[0].content == "App Side Project"
    assert proj_tasks[0].is_budget_task is True
    assert proj_tasks[0].session_max_minutes == 180
    assert proj_tasks[0].duration_minutes == 90  # session_min
    assert proj_tasks[0].remaining_hours == 20.0
    assert proj_tasks[0].deadline_pressure == "at_risk"


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
