from unittest.mock import MagicMock, patch

import pytest

from api.services.import_calendar import (
    PapyrusCalendarError,
    PapyrusCalendarScopeError,
    ensure_papyrus_calendar,
)


def _build_credentials_mock(scopes: list[str] | None = None):
    creds = MagicMock()
    creds.scopes = scopes or [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.app.created",
    ]
    return creds


def test_returns_existing_id_when_papyrus_calendar_already_present():
    supabase = MagicMock()
    supabase.from_().select().eq().single().execute.return_value.data = {
        "papyrus_calendar_id": "cached-id-123"
    }
    result = ensure_papyrus_calendar(
        user_id="user-1",
        supabase=supabase,
        credentials=_build_credentials_mock(),
        timezone_str="America/Vancouver",
    )
    assert result == "cached-id-123"


def test_finds_existing_calendar_by_summary_when_id_not_cached():
    supabase = MagicMock()
    supabase.from_().select().eq().single().execute.return_value.data = {
        "papyrus_calendar_id": None
    }
    with patch("api.services.import_calendar.build") as mock_build:
        service = mock_build.return_value
        service.calendarList().list().execute.return_value = {
            "items": [
                {"id": "primary", "summary": "Some other"},
                {"id": "papyrus-cal-id", "summary": "Papyrus"},
            ]
        }
        result = ensure_papyrus_calendar(
            user_id="user-1",
            supabase=supabase,
            credentials=_build_credentials_mock(),
            timezone_str="America/Vancouver",
        )
    assert result == "papyrus-cal-id"
    supabase.from_().update().eq().execute.assert_called()


def test_creates_new_calendar_when_none_exists():
    supabase = MagicMock()
    supabase.from_().select().eq().single().execute.return_value.data = {
        "papyrus_calendar_id": None
    }
    with patch("api.services.import_calendar.build") as mock_build:
        service = mock_build.return_value
        service.calendarList().list().execute.return_value = {"items": []}
        service.calendars().insert().execute.return_value = {"id": "newly-created-id"}
        result = ensure_papyrus_calendar(
            user_id="user-1",
            supabase=supabase,
            credentials=_build_credentials_mock(),
            timezone_str="America/Vancouver",
        )
    assert result == "newly-created-id"
    supabase.from_().update().eq().execute.assert_called()


def test_raises_scope_error_when_app_created_scope_missing():
    supabase = MagicMock()
    supabase.from_().select().eq().single().execute.return_value.data = {
        "papyrus_calendar_id": None
    }
    creds = _build_credentials_mock(scopes=[
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ])
    with patch("api.services.import_calendar.build") as mock_build:
        service = mock_build.return_value
        service.calendarList().list().execute.return_value = {"items": []}
        with pytest.raises(PapyrusCalendarScopeError):
            ensure_papyrus_calendar(
                user_id="user-1",
                supabase=supabase,
                credentials=creds,
                timezone_str="America/Vancouver",
            )
