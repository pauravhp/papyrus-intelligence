import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")

from unittest.mock import MagicMock, call
from datetime import date
import pytest


def _make_event_response(items=None):
    return {"items": items or []}


def test_get_events_does_not_call_calendar_list():
    """get_events must never call calendarList() — it uses the passed calendar_ids directly."""
    from src.calendar_client import get_events
    mock_svc = MagicMock()
    mock_svc.events.return_value.list.return_value.execute.return_value = _make_event_response()

    get_events(date.today(), calendar_ids=["primary"], service=mock_svc)

    mock_svc.calendarList.assert_not_called()


def test_get_events_queries_each_calendar_id():
    """get_events fetches from every calendar_id provided."""
    from src.calendar_client import get_events
    mock_svc = MagicMock()
    mock_svc.events.return_value.list.return_value.execute.return_value = _make_event_response()

    get_events(date.today(), calendar_ids=["primary", "work@co.com"], service=mock_svc)

    calls = mock_svc.events.return_value.list.call_args_list
    cal_ids_queried = [c.kwargs.get("calendarId") or c.args[0] for c in calls
                       if "calendarId" in (c.kwargs or {})]
    # Ensure both calendars were queried
    assert "primary" in str(mock_svc.events.return_value.list.call_args_list)
    assert "work@co.com" in str(mock_svc.events.return_value.list.call_args_list)


def test_get_events_empty_calendar_ids_returns_empty():
    """If calendar_ids is empty, no events are returned and no API call is made."""
    from src.calendar_client import get_events
    mock_svc = MagicMock()

    result = get_events(date.today(), calendar_ids=[], service=mock_svc)

    assert result == []
    mock_svc.events.assert_not_called()


def test_list_calendars_returns_structured_list():
    """list_calendars returns id/summary/background_color/access_role for each calendar."""
    from src.calendar_client import list_calendars
    mock_svc = MagicMock()
    mock_svc.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "primary", "summary": "Personal", "backgroundColor": "#4285f4", "accessRole": "owner"},
            {"id": "work@co.com", "summary": "Work", "backgroundColor": "#0b8043", "accessRole": "writer"},
        ]
    }

    result = list_calendars(mock_svc)

    assert len(result) == 2
    assert result[0] == {"id": "primary", "summary": "Personal", "background_color": "#4285f4", "access_role": "owner"}
    assert result[1] == {"id": "work@co.com", "summary": "Work", "background_color": "#0b8043", "access_role": "writer"}


def test_list_calendars_failure_returns_primary_fallback():
    """list_calendars returns a single primary entry if calendarList() throws."""
    from src.calendar_client import list_calendars
    mock_svc = MagicMock()
    mock_svc.calendarList.return_value.list.return_value.execute.side_effect = Exception("API down")

    result = list_calendars(mock_svc)

    assert len(result) == 1
    assert result[0]["id"] == "primary"
