"""
Unit tests for src/scheduler.py — pure logic, no API calls.

Test cases:
1. Normal weekday — standard morning buffer, single free window 10:30–23:00
2. Late night prior — extra 90min penalty shifts effective start to 12:00
3. Weekend rule (Friday) — nothing before 13:00 per context.json
4. Flamingo buffer — 15min each side creates correct free window boundaries
5. Overlapping event buffers — two close meetings merge into one blocked block
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.models import CalendarEvent
from src.scheduler import compute_free_windows

TZ = ZoneInfo("America/Vancouver")

# Canonical context matching context.json
BASE_CONTEXT = {
    "user": {"name": "Test", "timezone": "America/Vancouver"},
    "sleep": {
        "default_sleep_time": "01:00",
        "default_wake_time": "09:00",
        "morning_buffer_minutes": 90,
        "first_task_not_before": "10:30",
        "weekend_days": ["friday", "saturday", "sunday"],
        "weekend_nothing_before": "13:00",
        "late_night_threshold": "00:30",
        "no_tasks_after": "23:00",
    },
    "calendar_rules": {
        "flamingo": {
            "color_id": "4",
            "type": "meeting_call",
            "buffer_before_minutes": 15,
            "buffer_after_minutes": 15,
            "movable": False,
        },
        "banana": {
            "color_id": "5",
            "type": "event",
            "buffer_before_minutes": 30,
            "buffer_after_minutes": 30,
            "movable": False,
        },
    },
}


def make_event(
    summary: str,
    start_hour: int,
    start_min: int,
    end_hour: int,
    end_min: int,
    color_id: str | None = None,
    target_date: date | None = None,
    is_all_day: bool = False,
) -> CalendarEvent:
    d = target_date or date(2026, 4, 7)  # Tuesday
    start = datetime(d.year, d.month, d.day, start_hour, start_min, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, end_hour, end_min, tzinfo=TZ)
    return CalendarEvent(
        id="test-id",
        summary=summary,
        start=start,
        end=end,
        color_id=color_id,
        is_all_day=is_all_day,
    )


# ── 1. Normal weekday ─────────────────────────────────────────────────────────

def test_normal_weekday_no_events():
    """No events on a Tuesday: one big free window from 10:30 to 23:00."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT)

    assert len(windows) == 1
    w = windows[0]
    assert (w.start.hour, w.start.minute) == (10, 30)
    assert (w.end.hour, w.end.minute) == (23, 0)
    assert w.duration_minutes == 750  # 12h30m
    assert w.block_type == "morning"


def test_normal_weekday_splits_on_event():
    """An uncolored midday event splits the day into two free windows."""
    tuesday = date(2026, 4, 7)
    event = make_event("Lunch", 12, 0, 13, 0, color_id=None, target_date=tuesday)
    windows = compute_free_windows([event], tuesday, BASE_CONTEXT)

    assert len(windows) == 2
    assert (windows[0].start.hour, windows[0].start.minute) == (10, 30)
    assert (windows[0].end.hour, windows[0].end.minute) == (12, 0)
    assert (windows[1].start.hour, windows[1].start.minute) == (13, 0)
    assert (windows[1].end.hour, windows[1].end.minute) == (23, 0)


# ── 2. Late night prior adjustment ───────────────────────────────────────────

def test_late_night_prior_shifts_start():
    """
    late_night_prior=True adds 90min to wake time.
    Normal: wake 09:00 + 90min buffer = 10:30.
    Late night: wake 10:30 + 90min buffer = 12:00.
    """
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT, late_night_prior=True)

    assert len(windows) == 1
    w = windows[0]
    assert (w.start.hour, w.start.minute) == (12, 0)
    assert (w.end.hour, w.end.minute) == (23, 0)
    assert w.duration_minutes == 660  # 11h


# ── 3. Weekend noon rule ──────────────────────────────────────────────────────

def test_weekend_friday_nothing_before_1pm():
    """Friday: effective start must not be before 13:00 regardless of wake time."""
    friday = date(2026, 4, 10)
    windows = compute_free_windows([], friday, BASE_CONTEXT)

    assert len(windows) == 1
    w = windows[0]
    assert (w.start.hour, w.start.minute) == (13, 0)
    assert (w.end.hour, w.end.minute) == (23, 0)
    assert w.duration_minutes == 600  # 10h


def test_weekend_saturday():
    """Saturday is also a weekend day — same 13:00 rule."""
    saturday = date(2026, 4, 11)
    windows = compute_free_windows([], saturday, BASE_CONTEXT)

    assert len(windows) == 1
    assert (windows[0].start.hour, windows[0].start.minute) == (13, 0)


# ── 4. Flamingo buffer (15min each side) ─────────────────────────────────────

def test_flamingo_buffer_creates_correct_boundaries():
    """
    Meeting 14:00–15:00 with color_id "4" (Flamingo).
    Buffer before = 15min → gap ends at 13:45.
    Buffer after  = 15min → next gap starts at 15:15.
    """
    tuesday = date(2026, 4, 7)
    meeting = make_event("Team Meeting", 14, 0, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([meeting], tuesday, BASE_CONTEXT)

    assert len(windows) == 2

    before = windows[0]
    after = windows[1]

    assert (before.start.hour, before.start.minute) == (10, 30)
    assert (before.end.hour, before.end.minute) == (13, 45)

    assert (after.start.hour, after.start.minute) == (15, 15)
    assert (after.end.hour, after.end.minute) == (23, 0)


def test_banana_buffer_creates_correct_boundaries():
    """
    Event 14:00–15:00 with color_id "5" (Banana).
    Buffer before = 30min → gap ends at 13:30.
    Buffer after  = 30min → next gap starts at 15:30.
    """
    tuesday = date(2026, 4, 7)
    event = make_event("Conference", 14, 0, 15, 0, color_id="5", target_date=tuesday)
    windows = compute_free_windows([event], tuesday, BASE_CONTEXT)

    assert len(windows) == 2
    assert (windows[0].end.hour, windows[0].end.minute) == (13, 30)
    assert (windows[1].start.hour, windows[1].start.minute) == (15, 30)


# ── 5. Overlapping event buffers ─────────────────────────────────────────────

def test_overlapping_flamingo_buffers_merge():
    """
    Two Flamingo meetings close together so their buffers overlap:
      Meeting 1: 13:00–14:00 → blocked 12:45–14:15
      Meeting 2: 14:10–15:00 → blocked 13:55–15:15
    After merge: one block 12:45–15:15. No gap between them.
    """
    tuesday = date(2026, 4, 7)
    m1 = make_event("Meeting 1", 13, 0, 14, 0, color_id="4", target_date=tuesday)
    m2 = make_event("Meeting 2", 14, 10, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([m1, m2], tuesday, BASE_CONTEXT)

    # Should be exactly two windows: before 12:45 and after 15:15
    assert len(windows) == 2

    before = windows[0]
    after = windows[1]

    assert (before.start.hour, before.start.minute) == (10, 30)
    assert (before.end.hour, before.end.minute) == (12, 45)

    assert (after.start.hour, after.start.minute) == (15, 15)
    assert (after.end.hour, after.end.minute) == (23, 0)


def test_all_day_event_does_not_block_time():
    """All-day events occupy no time slot and should not reduce free windows."""
    tuesday = date(2026, 4, 7)
    all_day = CalendarEvent(
        id="all-day-id",
        summary="Holiday",
        start=datetime(2026, 4, 7, 0, 0, tzinfo=TZ),
        end=datetime(2026, 4, 8, 0, 0, tzinfo=TZ),
        color_id=None,
        is_all_day=True,
    )
    windows = compute_free_windows([all_day], tuesday, BASE_CONTEXT)

    assert len(windows) == 1
    assert (windows[0].start.hour, windows[0].start.minute) == (10, 30)
    assert (windows[0].end.hour, windows[0].end.minute) == (23, 0)
