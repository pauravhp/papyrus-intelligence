import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-secret")

from unittest.mock import MagicMock
from datetime import date


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

    list_mock = mock_svc.events.return_value.list
    assert list_mock.call_count == 2
    called_ids = {c.kwargs["calendarId"] for c in list_mock.call_args_list}
    assert called_ids == {"primary", "work@co.com"}


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


# ── build_gcal_service_from_credentials — RefreshError surfacing ──────────────


def _creds_data() -> dict:
    return {
        "token": "stale-access-token",
        "refresh_token": "rt-1",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-id",
        "client_secret": "test-secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "expiry": "2020-01-01T00:00:00Z",  # forces creds.expired = True
    }


def test_build_gcal_service_raises_reconnect_required_on_refresh_error(monkeypatch):
    """A google.auth.exceptions.RefreshError (e.g. invalid_scope) must surface
    as GcalReconnectRequired so routes can convert it to a structured signal
    instead of a 500."""
    import pytest
    from google.auth.exceptions import RefreshError

    from src.calendar_client import (
        GcalReconnectRequired,
        build_gcal_service_from_credentials,
    )

    def _raise_refresh_error(self, request):
        raise RefreshError("invalid_scope: Bad Request", {"error": "invalid_scope"})

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh",
        _raise_refresh_error,
    )

    with pytest.raises(GcalReconnectRequired) as exc_info:
        build_gcal_service_from_credentials(_creds_data(), "test-id", "test-secret")

    assert "invalid_scope" in str(exc_info.value)


def test_build_gcal_service_raises_reconnect_required_when_no_refresh_token():
    """Stored creds with no refresh_token = unrecoverable. Must surface as
    GcalReconnectRequired (not RuntimeError) so routes can act on it
    uniformly."""
    import pytest
    from src.calendar_client import (
        GcalReconnectRequired,
        build_gcal_service_from_credentials,
    )

    creds_data = _creds_data()
    del creds_data["refresh_token"]

    with pytest.raises((GcalReconnectRequired, ValueError)):
        # ValueError is from google-auth library when refresh_token missing
        # at construction; either is acceptable as "needs reconnect."
        build_gcal_service_from_credentials(creds_data, "test-id", "test-secret")
