"""
Tests for api.services.sync_detector — detects whether the user has Todoist's
GCal integration enabled (which would cause every confirmed Papyrus event to
appear twice on their calendar). See PRE-RELEASE.md #9 for the design rationale.
"""

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


def test_detect_returns_positive_when_todoist_calendar_present():
    """A calendar named 'Todoist' in the user's calendar list → detected=True."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "primary", "summary": "Primary"},
        {"id": "abc123@group.calendar.google.com", "summary": "Todoist"},
        {"id": "work@example.com", "summary": "Work"},
    ]):
        result = detect_todoist_gcal_sync(MagicMock())

    assert result["detected"] is True
    assert result["calendar_id"] == "abc123@group.calendar.google.com"


def test_detect_returns_negative_when_no_todoist_calendar():
    """No calendar matches → detected=False, calendar_id=None."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "primary", "summary": "Primary"},
        {"id": "work@example.com", "summary": "Work"},
        {"id": "personal@example.com", "summary": "Personal"},
    ]):
        result = detect_todoist_gcal_sync(MagicMock())

    assert result["detected"] is False
    assert result["calendar_id"] is None


def test_detect_is_case_insensitive_and_prefix_only():
    """Match is /^Todoist/i — 'todoist' (lowercase) and 'Todoist Tasks' both hit."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "x", "summary": "todoist"},  # lowercase
    ]):
        assert detect_todoist_gcal_sync(MagicMock())["detected"] is True

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "y", "summary": "Todoist Tasks"},  # prefix match
    ]):
        assert detect_todoist_gcal_sync(MagicMock())["detected"] is True


def test_detect_does_not_match_substring_in_middle():
    """A calendar named 'My Todoist Backup' should NOT match — only prefix."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "z", "summary": "My Todoist Backup"},
    ]):
        result = detect_todoist_gcal_sync(MagicMock())
    assert result["detected"] is False


def test_detect_returns_first_match_when_multiple():
    """If somehow multiple Todoist-named calendars exist, return the first."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "first", "summary": "Todoist"},
        {"id": "second", "summary": "Todoist Archive"},
    ]):
        result = detect_todoist_gcal_sync(MagicMock())

    assert result["detected"] is True
    assert result["calendar_id"] == "first"


def test_detect_returns_negative_when_list_calendars_returns_empty():
    """list_calendars failure path returns just primary fallback or empty list."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[]):
        result = detect_todoist_gcal_sync(MagicMock())

    assert result["detected"] is False
    assert result["calendar_id"] is None


def test_detect_handles_calendar_with_no_summary():
    """Defensive: a calendar dict missing 'summary' shouldn't crash."""
    from api.services.sync_detector import detect_todoist_gcal_sync

    with patch("api.services.sync_detector.list_calendars", return_value=[
        {"id": "x"},  # no summary key
        {"id": "y", "summary": "Todoist"},
    ]):
        result = detect_todoist_gcal_sync(MagicMock())

    assert result["detected"] is True
    assert result["calendar_id"] == "y"
