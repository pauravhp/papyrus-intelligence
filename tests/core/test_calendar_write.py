from unittest.mock import MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo


def _make_service():
    svc = MagicMock()
    svc.events.return_value.insert.return_value.execute.return_value = {"id": "gcal-evt-001"}
    svc.events.return_value.delete.return_value.execute.return_value = None
    return svc


def test_create_event_returns_event_id():
    from src.calendar_client import create_event
    tz = ZoneInfo("America/Vancouver")
    start = datetime(2026, 4, 12, 9, 0, tzinfo=tz)
    end = datetime(2026, 4, 12, 10, 30, tzinfo=tz)
    svc = _make_service()
    event_id = create_event(svc, "Deep Work", start, end, "America/Vancouver")
    assert event_id == "gcal-evt-001"
    svc.events.return_value.insert.assert_called_once()


def test_delete_event_calls_service():
    from src.calendar_client import delete_event
    svc = _make_service()
    delete_event(svc, "gcal-evt-001")
    svc.events.return_value.delete.assert_called_once_with(
        calendarId="primary", eventId="gcal-evt-001"
    )


def test_build_gcal_service_refreshes_expired_token():
    from src.calendar_client import build_gcal_service_from_credentials
    creds_data = {
        "token": "old-token",
        "refresh_token": "rtoken",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csec",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
    }
    mock_creds = MagicMock()
    mock_creds.valid = True
    with patch("src.calendar_client.Credentials.from_authorized_user_info", return_value=mock_creds), \
         patch("src.calendar_client.build") as mock_build:
        mock_build.return_value = MagicMock()
        svc, refreshed = build_gcal_service_from_credentials(creds_data, "cid", "csec")
    mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds)
    assert svc is not None
