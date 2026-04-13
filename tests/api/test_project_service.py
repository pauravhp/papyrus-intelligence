import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from unittest.mock import MagicMock
import pytest
from api.services.project_service import (
    get_active_projects,
    create_project,
    update_project,
    delete_project,
    reset_project,
    log_session,
)


def _make_sb(rows=None, updated_row=None):
    sb = MagicMock()
    # select chain
    sb.from_.return_value.select.return_value.eq.return_value.gt.return_value.order.return_value.execute.return_value.data = rows or []
    # single row fetch (for update/reset/log)
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = updated_row
    # update chain
    sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [updated_row] if updated_row else []
    # insert chain
    sb.from_.return_value.insert.return_value.execute.return_value.data = [updated_row] if updated_row else []
    # delete chain
    sb.from_.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    return sb


def test_get_active_projects_returns_list_with_pressure():
    row = {
        "id": 1, "project_name": "App Project", "total_budget_hours": 22.0,
        "remaining_hours": 20.0, "session_min_minutes": 90, "session_max_minutes": 180,
        "deadline": None, "priority": 3, "created_at": "2026-04-12T00:00:00",
        "updated_at": "2026-04-12T00:00:00",
    }
    sb = _make_sb(rows=[row])
    result = get_active_projects("user-123", sb)
    assert len(result) == 1
    assert result[0]["project_name"] == "App Project"
    assert result[0]["deadline_pressure"] == "no_deadline"


def test_create_project_inserts_row():
    new_row = {
        "id": 2, "project_name": "GPU Study", "total_budget_hours": 10.0,
        "remaining_hours": 10.0, "session_min_minutes": 45, "session_max_minutes": 60,
        "deadline": None, "priority": 3, "created_at": "2026-04-12T00:00:00",
        "updated_at": "2026-04-12T00:00:00",
    }
    sb = MagicMock()
    sb.from_.return_value.insert.return_value.execute.return_value.data = [new_row]
    result = create_project("user-123", sb, name="GPU Study", total_hours=10.0,
                            session_min=45, session_max=60)
    assert result["project_name"] == "GPU Study"
    assert result["remaining_hours"] == 10.0


def test_log_session_decrements_remaining():
    updated = {
        "id": 1, "project_name": "App", "total_budget_hours": 22.0,
        "remaining_hours": 18.5, "session_min_minutes": 90, "session_max_minutes": 180,
        "deadline": None, "priority": 3, "created_at": "x", "updated_at": "x",
    }
    sb = MagicMock()
    # Mock initial select to return current remaining_hours
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {"remaining_hours": 20.0}
    sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.select.return_value.single.return_value.execute.return_value.data = updated
    result = log_session("user-123", sb, project_id=1, hours_worked=1.5)
    assert result["remaining_hours"] == 18.5
    # Verify the update was called with the correctly computed new_remaining (20.0 - 1.5 = 18.5)
    update_call_args = sb.from_.return_value.update.call_args[0][0]
    assert update_call_args["remaining_hours"] == 18.5


def test_delete_project_calls_delete():
    sb = MagicMock()
    sb.from_.return_value.delete.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    delete_project("user-123", sb, project_id=1)
    sb.from_.assert_called_with("project_budgets")


def test_reset_project_restores_hours():
    updated = {
        "id": 1, "project_name": "App", "total_budget_hours": 22.0,
        "remaining_hours": 22.0, "session_min_minutes": 90, "session_max_minutes": 180,
        "deadline": None, "priority": 3, "created_at": "x", "updated_at": "x",
    }
    sb = MagicMock()
    # Mock initial select to return total_budget_hours
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {"total_budget_hours": 22.0}
    sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.select.return_value.single.return_value.execute.return_value.data = updated
    result = reset_project("user-123", sb, project_id=1)
    assert result["remaining_hours"] == 22.0
    # Verify the update was called with remaining_hours set to total (22.0)
    update_call_args = sb.from_.return_value.update.call_args[0][0]
    assert update_call_args["remaining_hours"] == 22.0


def test_update_project_patches_fields():
    updated = {
        "id": 1, "project_name": "App", "total_budget_hours": 22.0,
        "remaining_hours": 20.0, "session_min_minutes": 60, "session_max_minutes": 120,
        "deadline": "2026-05-01", "priority": 4, "created_at": "x", "updated_at": "x",
    }
    sb = MagicMock()
    sb.from_.return_value.update.return_value.eq.return_value.eq.return_value.select.return_value.single.return_value.execute.return_value.data = updated
    result = update_project("user-123", sb, project_id=1, session_min=60,
                            session_max=120, deadline="2026-05-01", priority=4)
    assert result["session_min_minutes"] == 60
    assert result["deadline"] == "2026-05-01"
