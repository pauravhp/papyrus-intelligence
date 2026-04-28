import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.auth import require_beta_access


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _patch_beta_access():
    # Use app.dependency_overrides — monkeypatching the callable does not
    # work for FastAPI because the dependency graph is resolved at import time.
    app.dependency_overrides[require_beta_access] = lambda: {"sub": "user-1"}
    yield
    app.dependency_overrides.pop(require_beta_access, None)


client = TestClient(app)


@patch("api.routes.import_tasks.parse_migration_dump")
def test_convert_happy_path(mock_parse):
    mock_parse.return_value = {
        "tasks": [{
            "content": "Draft post",
            "priority": 3,
            "duration_minutes": 60,
            "category_label": "@deep-work",
            "deadline": None,
            "reasoning": "writing task",
        }],
        "rhythms": [],
        "unmatched": [],
    }
    resp = client.post(
        "/api/import/convert",
        json={"raw_text": "Draft post for the launch announcement"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["content"] == "Draft post"


def test_convert_rejects_short_input():
    resp = client.post(
        "/api/import/convert",
        json={"raw_text": "hi"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "input_too_short"


def test_convert_rejects_long_input():
    resp = client.post(
        "/api/import/convert",
        json={"raw_text": "x" * 5_001},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "input_too_long"


@patch("api.routes.import_tasks.parse_migration_dump")
def test_convert_502_on_double_llm_failure(mock_parse):
    from api.services.migration_parser import MigrationParseError
    mock_parse.side_effect = MigrationParseError("boom")
    resp = client.post(
        "/api/import/convert",
        json={"raw_text": "paste with enough characters here please"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 502


@patch("api.routes.import_tasks._build_todoist_client")
@patch("api.routes.import_tasks.create_rhythm")
def test_commit_writes_tasks_and_rhythms(mock_create_rhythm, mock_build_client):
    mock_client = MagicMock()
    mock_client.create_task.return_value = "task-id-1"
    mock_build_client.return_value = mock_client
    mock_create_rhythm.return_value = {"id": 7}

    resp = client.post(
        "/api/import/commit",
        json={
            "tasks": [{
                "content": "Draft post",
                "priority": 3,
                "duration_minutes": 60,
                "category_label": "@deep-work",
                "deadline": None,
                "reasoning": "writing task",
            }],
            "rhythms": [{
                "name": "Morning workout",
                "scheduling_hint": "mornings only",
                "sessions_per_week": 5,
                "session_min_minutes": 30,
                "session_max_minutes": 60,
                "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
                "reasoning": "explicit recurrence",
            }],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tasks_created"] == 1
    assert body["rhythms_created"] == 1
    assert body["errors"] == []
    assert body["todoist_reconnect_required"] is False

    args, kwargs = mock_client.create_task.call_args
    assert kwargs["content"] == "Draft post"
    assert kwargs["priority"] == 3
    assert "60min" in kwargs["labels"]
    assert "deep-work" in kwargs["labels"]


@patch("api.routes.import_tasks._build_todoist_client")
@patch("api.routes.import_tasks.create_rhythm")
def test_commit_records_per_item_failures(mock_create_rhythm, mock_build_client):
    mock_client = MagicMock()
    mock_client.create_task.side_effect = [Exception("429"), "task-id-2"]
    mock_build_client.return_value = mock_client

    resp = client.post(
        "/api/import/commit",
        json={
            "tasks": [
                {"content": "A", "priority": 3, "duration_minutes": 30,
                 "category_label": None, "deadline": None, "reasoning": ""},
                {"content": "B", "priority": 3, "duration_minutes": 30,
                 "category_label": None, "deadline": None, "reasoning": ""},
            ],
            "rhythms": [],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tasks_created"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["kind"] == "task"

    # Verify the second (successful) task's labels did not include a stripped-None
    second_call_kwargs = mock_client.create_task.call_args_list[1].kwargs
    assert second_call_kwargs["labels"] == ["30min"]


@patch("api.routes.import_tasks._build_todoist_client")
def test_commit_bails_on_todoist_401(mock_build_client):
    mock_client = MagicMock()
    mock_client.create_task.side_effect = RuntimeError("Todoist API auth failed — token revoked")
    mock_build_client.return_value = mock_client

    resp = client.post(
        "/api/import/commit",
        json={
            "tasks": [{"content": "A", "priority": 3, "duration_minutes": 30,
                       "category_label": None, "deadline": None, "reasoning": ""}],
            "rhythms": [],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "todoist_reconnect_required"


@patch("api.routes.import_tasks._build_todoist_client")
@patch("api.routes.import_tasks.create_rhythm")
def test_commit_records_per_rhythm_failures(mock_create_rhythm, mock_build_client):
    mock_client = MagicMock()
    mock_client.create_task.return_value = "task-id-1"
    mock_build_client.return_value = mock_client
    mock_create_rhythm.side_effect = [Exception("supabase down"), {"id": 7}]

    resp = client.post(
        "/api/import/commit",
        json={
            "tasks": [],
            "rhythms": [
                {"name": "A", "scheduling_hint": "", "sessions_per_week": 3,
                 "session_min_minutes": 30, "session_max_minutes": 60,
                 "days_of_week": ["mon", "wed", "fri"], "reasoning": ""},
                {"name": "B", "scheduling_hint": "", "sessions_per_week": 5,
                 "session_min_minutes": 30, "session_max_minutes": 60,
                 "days_of_week": ["mon", "tue", "wed", "thu", "fri"], "reasoning": ""},
            ],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rhythms_created"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["kind"] == "rhythm"
    assert body["errors"][0]["name"] == "A"


@patch("api.routes.import_tasks._build_todoist_client")
def test_commit_empty_payload_succeeds(mock_build_client):
    mock_build_client.return_value = MagicMock()
    resp = client.post(
        "/api/import/commit",
        json={"tasks": [], "rhythms": []},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tasks_created"] == 0
    assert body["rhythms_created"] == 0
    assert body["errors"] == []


@patch("api.routes.import_tasks.get_valid_todoist_token")
def test_commit_returns_400_when_token_error(mock_get_token):
    from api.services.todoist_token import TodoistTokenError
    mock_get_token.side_effect = TodoistTokenError("No Todoist token stored for user")
    resp = client.post(
        "/api/import/commit",
        json={"tasks": [], "rhythms": []},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "todoist_reconnect_required"
