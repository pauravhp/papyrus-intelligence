from datetime import date
from unittest.mock import MagicMock, patch

from src.todoist_client import TodoistClient


def test_get_completed_task_ids_for_date_filters_by_local_day():
    """Returns the set of task IDs completed on target_date in user's local tz."""
    client = TodoistClient(api_token="test_token")
    target = date(2026, 4, 29)
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "items": [
            {"task_id": "111", "completed_at": "2026-04-29T15:00:00Z"},
            {"task_id": "222", "completed_at": "2026-04-29T22:00:00Z"},
        ]
    }
    with patch("src.todoist_client.requests.post", return_value=fake_resp) as post:
        result = client.get_completed_task_ids_for_date(target)
    assert result == {"111", "222"}
    args, kwargs = post.call_args
    assert "sync/v9/completed/get_all" in args[0]
    assert kwargs["json"]["since"].startswith("2026-04-29")
    assert kwargs["json"]["until"].startswith("2026-04-30")


def test_get_completed_task_ids_for_date_returns_empty_on_404():
    """Sync API not available (free-tier quirk) — degrade gracefully."""
    client = TodoistClient(api_token="test_token")
    fake_resp = MagicMock()
    fake_resp.status_code = 404
    with patch("src.todoist_client.requests.post", return_value=fake_resp):
        result = client.get_completed_task_ids_for_date(date(2026, 4, 29))
    assert result == set()


def test_get_completed_task_ids_for_date_raises_on_auth_failure():
    client = TodoistClient(api_token="bad_token")
    fake_resp = MagicMock()
    fake_resp.status_code = 401
    with patch("src.todoist_client.requests.post", return_value=fake_resp):
        try:
            client.get_completed_task_ids_for_date(date(2026, 4, 29))
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "auth failed" in str(exc).lower()
