"""
Unit tests for src/scheduler.py — pure logic, no API calls.

Test cases:
1. Normal weekday — morning buffer, all windows ≤ 90 min, first starts at 10:30
2. Late night prior — extra 90min penalty, first window starts at 12:00
3. Weekend rule (Friday/Saturday) — nothing before 13:00
4. Flamingo buffer — 15min each side creates correct gap boundaries
5. Overlapping event buffers — merged block, no window sneaks through the gap
6. All-day event — does not consume any clock time
7. Chunking — 90-min cap and 15-min breaks are enforced on a long window
8. Banana buffer — 30min each side
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.models import CalendarEvent, FreeWindow
from src.scheduler import (
    BREAK_BETWEEN_WINDOWS_MINUTES,
    MAX_WINDOW_MINUTES,
    compute_free_windows,
    pack_schedule,
)

TZ = ZoneInfo("America/Vancouver")

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
        id="test-id", summary=summary,
        start=start, end=end,
        color_id=color_id, is_all_day=is_all_day,
    )


def _hm(dt: datetime) -> tuple[int, int]:
    return dt.hour, dt.minute


# ── 1. Normal weekday ─────────────────────────────────────────────────────────

def test_normal_weekday_first_window_starts_at_morning_buffer():
    """First schedulable window must start exactly at 10:30 on a Tuesday."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT)

    assert len(windows) >= 1
    assert _hm(windows[0].start) == (10, 30)


def test_normal_weekday_returns_single_continuous_window():
    """An empty weekday returns one raw continuous window from 10:30 to 23:00 (750 min).
    compute_free_windows no longer pre-chunks — pack_schedule owns all break logic."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT)

    assert len(windows) == 1
    assert windows[0].duration_minutes == 750  # 10:30 to 23:00


def test_normal_weekday_last_window_ends_at_or_before_day_end():
    """No window may extend past 23:00."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT)

    for w in windows:
        assert (w.end.hour, w.end.minute) <= (23, 0), f"Window ends after 23:00: {w.end}"


def test_windows_separated_by_calendar_event_have_correct_gap():
    """Windows separated by a calendar event have a gap matching the event + buffers."""
    tuesday = date(2026, 4, 7)
    # Flamingo event 14:00–15:00: adds 15min buffer each side → blocked 13:45–15:15
    meeting = make_event("Meeting", 14, 0, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([meeting], tuesday, BASE_CONTEXT)

    # Should have exactly 2 windows: before the blocked zone and after
    assert len(windows) == 2
    gap = int((windows[1].start - windows[0].end).total_seconds() / 60)
    # Gap = 15min buffer before (13:45 end) + 60min event + 15min buffer after = 90min
    assert gap == 90


# ── 2. Late night prior ───────────────────────────────────────────────────────

def test_late_night_prior_shifts_first_window():
    """
    late_night_prior=True adds 90min to wake.
    Normal: wake 09:00 + 90min buffer = 10:30.
    Late night: wake 10:30 + 90min buffer = 12:00.
    """
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, BASE_CONTEXT, late_night_prior=True)

    assert len(windows) >= 1
    assert _hm(windows[0].start) == (12, 0)


# ── 3. Weekend rule ───────────────────────────────────────────────────────────

def test_weekend_friday_first_window_at_1pm():
    """Friday: first window must not start before 13:00."""
    friday = date(2026, 4, 10)
    windows = compute_free_windows([], friday, BASE_CONTEXT)

    assert len(windows) >= 1
    assert _hm(windows[0].start) == (13, 0)


def test_weekend_saturday_first_window_at_1pm():
    saturday = date(2026, 4, 11)
    windows = compute_free_windows([], saturday, BASE_CONTEXT)

    assert len(windows) >= 1
    assert _hm(windows[0].start) == (13, 0)


# ── 4. Flamingo buffer (15 min each side) ─────────────────────────────────────

def test_flamingo_buffer_pre_event_window_ends_correctly():
    """
    Meeting 14:00–15:00 (Flamingo). Buffer before = 15min.
    The last window ending before the meeting must end at 13:45.
    """
    tuesday = date(2026, 4, 7)
    meeting = make_event("Team Meeting", 14, 0, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([meeting], tuesday, BASE_CONTEXT)

    before = [w for w in windows if w.end <= meeting.start]
    assert before, "Expected at least one window before the meeting"
    assert _hm(before[-1].end) == (13, 45)


def test_flamingo_buffer_post_event_window_starts_correctly():
    """
    Meeting 14:00–15:00 (Flamingo). Buffer after = 15min.
    The first window starting after the meeting must start at 15:15.
    """
    tuesday = date(2026, 4, 7)
    meeting = make_event("Team Meeting", 14, 0, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([meeting], tuesday, BASE_CONTEXT)

    event_end = datetime(2026, 4, 7, 15, 0, tzinfo=TZ)
    after = [w for w in windows if w.start >= event_end]
    assert after, "Expected at least one window after the meeting"
    assert _hm(after[0].start) == (15, 15)


# ── 5. Overlapping event buffers ─────────────────────────────────────────────

def test_overlapping_flamingo_buffers_no_gap_window():
    """
    Meeting 1: 13:00–14:00 → blocked 12:45–14:15
    Meeting 2: 14:10–15:00 → blocked 13:55–15:15
    After merge: 12:45–15:15 is one solid blocked block.
    No schedulable window should appear inside that range.
    """
    tuesday = date(2026, 4, 7)
    m1 = make_event("Meeting 1", 13, 0, 14, 0, color_id="4", target_date=tuesday)
    m2 = make_event("Meeting 2", 14, 10, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([m1, m2], tuesday, BASE_CONTEXT)

    blocked_start = datetime(2026, 4, 7, 12, 45, tzinfo=TZ)
    blocked_end = datetime(2026, 4, 7, 15, 15, tzinfo=TZ)

    for w in windows:
        # No window should overlap the merged blocked interval
        assert not (w.start < blocked_end and w.end > blocked_start), (
            f"Window {w.start}–{w.end} overlaps the blocked range 12:45–15:15"
        )


def test_overlapping_flamingo_buffers_correct_boundary_windows():
    """Pre-merge window ends at 12:45; post-merge window starts at 15:15."""
    tuesday = date(2026, 4, 7)
    m1 = make_event("Meeting 1", 13, 0, 14, 0, color_id="4", target_date=tuesday)
    m2 = make_event("Meeting 2", 14, 10, 15, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([m1, m2], tuesday, BASE_CONTEXT)

    blocked_start = datetime(2026, 4, 7, 12, 45, tzinfo=TZ)
    blocked_end = datetime(2026, 4, 7, 15, 15, tzinfo=TZ)

    before = [w for w in windows if w.end <= blocked_start]
    after = [w for w in windows if w.start >= blocked_end]

    assert before, "Expected windows before the blocked range"
    assert after, "Expected windows after the blocked range"
    assert _hm(before[-1].end) == (12, 45)
    assert _hm(after[0].start) == (15, 15)


# ── 6. All-day event ──────────────────────────────────────────────────────────

def test_all_day_event_does_not_block_time():
    """All-day events occupy no clock time — windows identical to empty day."""
    tuesday = date(2026, 4, 7)
    all_day = CalendarEvent(
        id="all-day", summary="Holiday",
        start=datetime(2026, 4, 7, 0, 0, tzinfo=TZ),
        end=datetime(2026, 4, 8, 0, 0, tzinfo=TZ),
        color_id=None, is_all_day=True,
    )
    windows_with = compute_free_windows([all_day], tuesday, BASE_CONTEXT)
    windows_without = compute_free_windows([], tuesday, BASE_CONTEXT)

    assert len(windows_with) == len(windows_without)
    assert _hm(windows_with[0].start) == _hm(windows_without[0].start)


# ── 7. Raw window (no pre-chunking) ───────────────────────────────────────────

def test_large_gap_returns_single_continuous_window():
    """A 240-min gap between two events returns as ONE raw continuous window.
    compute_free_windows no longer chunks — pack_schedule handles break insertion."""
    tuesday = date(2026, 4, 7)
    e1 = make_event("Block A", 10, 30, 11, 0, target_date=tuesday)   # blocks 10:30-11:00
    e2 = make_event("Block B", 15, 0, 23, 0, target_date=tuesday)    # blocks 15:00-23:00
    # Free gap: 11:00–15:00 = 240 min → returned as a single window
    windows = compute_free_windows([e1, e2], tuesday, BASE_CONTEXT)

    # Only one gap: 11:00–15:00
    assert len(windows) == 1
    assert windows[0].duration_minutes == 240
    assert _hm(windows[0].start) == (11, 0)
    assert _hm(windows[0].end) == (15, 0)


def test_small_gap_returns_single_window():
    """A small gap (< 90 min) is returned unchanged as one window."""
    tuesday = date(2026, 4, 7)
    # Events that leave a 45-min gap: effective start 10:30, event starts at 11:15
    event = make_event("Quick call", 11, 15, 12, 0, target_date=tuesday)
    windows = compute_free_windows([event], tuesday, BASE_CONTEXT)

    # First window: 10:30–11:15 = 45 min
    assert windows[0].duration_minutes == 45


# ── 8. Banana buffer (30 min each side) ──────────────────────────────────────

def test_banana_buffer_creates_correct_boundaries():
    """
    Event 14:00–15:00 with color_id "5" (Banana).
    Buffer before = 30min → pre-event windows end at 13:30.
    Buffer after  = 30min → post-event windows start at 15:30.
    """
    tuesday = date(2026, 4, 7)
    event = make_event("Conference", 14, 0, 15, 0, color_id="5", target_date=tuesday)
    windows = compute_free_windows([event], tuesday, BASE_CONTEXT)

    event_start = datetime(2026, 4, 7, 14, 0, tzinfo=TZ)
    event_end = datetime(2026, 4, 7, 15, 0, tzinfo=TZ)
    buf_start = datetime(2026, 4, 7, 13, 30, tzinfo=TZ)
    buf_end = datetime(2026, 4, 7, 15, 30, tzinfo=TZ)

    before = [w for w in windows if w.end <= buf_start]
    after = [w for w in windows if w.start >= buf_end]

    assert before, "Expected windows before the banana buffer"
    assert after, "Expected windows after the banana buffer"
    assert _hm(before[-1].end) == (13, 30)
    assert _hm(after[0].start) == (15, 30)


# ── pack_schedule tests ────────────────────────────────────────────────────────

def _make_window(
    start_hour: int,
    start_min: int,
    end_hour: int,
    end_min: int,
    block_type: str = "morning",
    target_date: date | None = None,
) -> FreeWindow:
    d = target_date or date(2026, 4, 7)
    start = datetime(d.year, d.month, d.day, start_hour, start_min, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, end_hour, end_min, tzinfo=TZ)
    return FreeWindow(
        start=start, end=end,
        duration_minutes=int((end - start).total_seconds() / 60),
        block_type=block_type,
    )


def _make_task(
    task_id: str,
    name: str,
    duration: int,
    can_be_split: bool = False,
    break_after: int = 0,
    flags: list[str] | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "task_name": name,
        "duration_minutes": duration,
        "can_be_split": can_be_split,
        "break_after_minutes": break_after,
        "block_label": "test",
        "placement_reason": "test",
        "scheduling_flags": flags or [],
    }


# ── 9. Normal packing — three tasks across two windows ────────────────────────

def test_pack_normal_all_tasks_scheduled():
    """Three tasks that collectively fit in two windows are all placed."""
    tuesday = date(2026, 4, 7)
    windows = [
        _make_window(10, 30, 12, 0),   # 90 min
        _make_window(12, 15, 13, 45),  # 90 min
    ]
    tasks = [
        _make_task("1", "Task A", 60),
        _make_task("2", "Task B", 30),
        _make_task("3", "Task C", 45),
    ]
    blocks, pushed = pack_schedule(tasks, windows, BASE_CONTEXT, target_date=tuesday)

    assert len(blocks) == 3
    assert len(pushed) == 0
    # Task A starts at window open
    assert _hm(blocks[0].start_time) == (10, 30)
    assert _hm(blocks[0].end_time) == (11, 30)
    # Task B picks up right after A
    assert _hm(blocks[1].start_time) == (11, 30)
    assert _hm(blocks[1].end_time) == (12, 0)
    # Task C goes to second window
    assert _hm(blocks[2].start_time) == (12, 15)


# ── 10. Overflow — second task pushed when no window left ─────────────────────

def test_pack_overflow_task_pushed_to_tomorrow():
    """Task that can't fit in any remaining window is pushed to the next day."""
    tuesday = date(2026, 4, 7)
    windows = [_make_window(10, 30, 12, 0)]  # 90 min, single window
    tasks = [
        _make_task("1", "Task A", 90),  # fills the entire window
        _make_task("2", "Task B", 30),  # no window left
    ]
    blocks, pushed = pack_schedule(tasks, windows, BASE_CONTEXT, target_date=tuesday)

    assert len(blocks) == 1
    assert len(pushed) == 1
    assert pushed[0]["task_id"] == "2"
    assert pushed[0]["suggested_date"] == "2026-04-08"


# ── 11. Split task — @2h task splits across two windows ───────────────────────

def test_pack_split_task_spans_two_windows():
    """A 120-min can_be_split task fills window 1 (90min) and continues in window 2."""
    tuesday = date(2026, 4, 7)
    windows = [
        _make_window(10, 30, 12, 0),   # 90 min
        _make_window(12, 15, 13, 45),  # 90 min
    ]
    tasks = [_make_task("1", "Big Task", 120, can_be_split=True)]
    blocks, pushed = pack_schedule(tasks, windows, BASE_CONTEXT, target_date=tuesday)

    assert len(blocks) == 2
    assert len(pushed) == 0
    assert blocks[0].split_session is True
    assert blocks[0].split_part == 1
    assert blocks[1].split_session is True
    assert blocks[1].split_part == 2
    # Combined duration must equal original
    assert blocks[0].duration_minutes + blocks[1].duration_minutes == 120
    # Part 1 ends at window 1's end; part 2 starts at window 2's start
    assert _hm(blocks[0].end_time) == (12, 0)
    assert _hm(blocks[1].start_time) == (12, 15)


# ── 12. Forced break — 90 min continuous triggers 15-min rest ─────────────────

def test_pack_forced_ultradian_break_after_90min():
    """
    After 90 min of continuous work, a 15-min break is enforced before the next task.
    Uses a single large window to make the forced break visible.
    """
    tuesday = date(2026, 4, 7)
    windows = [_make_window(10, 30, 14, 30)]  # 240-min window
    tasks = [
        _make_task("1", "Long Task", 90),   # 10:30–12:00 (continuous = 90)
        _make_task("2", "Short Task", 30),  # forced break → starts 12:15
    ]
    blocks, pushed = pack_schedule(tasks, windows, BASE_CONTEXT, target_date=tuesday)

    assert len(blocks) == 2
    assert len(pushed) == 0
    assert _hm(blocks[0].start_time) == (10, 30)
    assert _hm(blocks[0].end_time) == (12, 0)
    # 15-min break enforced → next task starts at 12:15
    assert _hm(blocks[1].start_time) == (12, 15)


# ── 13. can_be_split=False overflow — task skips to next window ───────────────

def test_pack_no_split_moves_to_next_window():
    """A non-splittable task that overflows window 1 is placed in window 2."""
    tuesday = date(2026, 4, 7)
    windows = [
        _make_window(10, 30, 11, 0),   # 30 min — too small for 60-min task
        _make_window(11, 15, 12, 45),  # 90 min — fits
    ]
    tasks = [_make_task("1", "Task A", 60, can_be_split=False)]
    blocks, pushed = pack_schedule(tasks, windows, BASE_CONTEXT, target_date=tuesday)

    assert len(blocks) == 1
    assert len(pushed) == 0
    assert _hm(blocks[0].start_time) == (11, 15)
    assert blocks[0].duration_minutes == 60


# ── daily_blocks tests ────────────────────────────────────────────────────────

DAILY_BLOCKS_CONTEXT = {
    **BASE_CONTEXT,
    "daily_blocks": [
        {
            "name": "Lunch",
            "start": "13:00",
            "end": "14:00",
            "days": "all",
            "movable": False,
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
        },
        {
            "name": "Evening snack",
            "start": "17:00",
            "end": "17:45",
            "days": "all",
            "movable": False,
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
        },
        {
            "name": "Gym",
            "start": "07:00",
            "end": "08:30",
            "days": "weekdays",
            "movable": False,
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
        },
    ],
}


def test_daily_block_lunch_splits_window():
    """Lunch 13:00–14:00 splits a continuous day into two windows."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, DAILY_BLOCKS_CONTEXT)

    # Window 1: 10:30–13:00 | Lunch 13:00–14:00 | Window 2: 14:00–17:00 | Snack | Window 3: 17:45–23:00
    starts = [_hm(w.start) for w in windows]
    ends = [_hm(w.end) for w in windows]

    # Lunch must not appear inside any window
    for w in windows:
        assert not (w.start < datetime(2026, 4, 7, 14, 0, tzinfo=TZ) and
                    w.end > datetime(2026, 4, 7, 13, 0, tzinfo=TZ)), (
            f"Window {w.start}–{w.end} overlaps Lunch block"
        )

    # At least one window ends at or before 13:00
    assert any(e <= (13, 0) for e in ends), "Expected a window ending by 13:00"
    # At least one window starts at or after 14:00
    assert any(s >= (14, 0) for s in starts), "Expected a window starting at 14:00 or later"


def test_daily_block_evening_snack_creates_gap():
    """Evening snack 17:00–17:45 creates a gap — window before ends at 17:00, after starts at 17:45."""
    tuesday = date(2026, 4, 7)
    windows = compute_free_windows([], tuesday, DAILY_BLOCKS_CONTEXT)

    snack_start = datetime(2026, 4, 7, 17, 0, tzinfo=TZ)
    snack_end = datetime(2026, 4, 7, 17, 45, tzinfo=TZ)

    for w in windows:
        assert not (w.start < snack_end and w.end > snack_start), (
            f"Window {w.start}–{w.end} overlaps Evening snack"
        )

    ends = [_hm(w.end) for w in windows]
    starts = [_hm(w.start) for w in windows]
    assert any(e <= (17, 0) for e in ends), "Expected a window ending by 17:00"
    assert any(s >= (17, 45) for s in starts), "Expected a window starting at 17:45 or later"


def test_weekdays_only_block_skips_saturday():
    """A block with days='weekdays' must NOT be applied on Saturday.

    We use a no-weekend-penalty context so effective_start is 10:30.
    A weekdays-only block at 11:00–12:00 should NOT appear, leaving a single
    continuous window from 10:30 to 23:00 (minus other daily_blocks).
    If it were incorrectly applied, the 10:30–11:00 and 12:00–... windows
    would be separate.
    """
    # Context with no weekend_days so effective_start = 10:30 on Saturday
    ctx_no_weekend = {
        **BASE_CONTEXT,
        "sleep": {
            **BASE_CONTEXT["sleep"],
            "weekend_days": [],   # no weekend restriction
        },
        "daily_blocks": [
            {
                "name": "Weekday block",
                "start": "11:00",
                "end": "12:00",
                "days": "weekdays",
                "movable": False,
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
            }
        ],
    }
    saturday = date(2026, 4, 11)  # Saturday
    windows = compute_free_windows([], saturday, ctx_no_weekend)

    # If the weekdays block is CORRECTLY skipped on Saturday, we get one
    # continuous window from 10:30–23:00.
    assert len(windows) == 1, (
        f"Expected 1 window (weekdays block skipped on Saturday), got {len(windows)}"
    )
    assert _hm(windows[0].start) == (10, 30)
    assert _hm(windows[0].end) == (23, 0)


def test_daily_block_and_gcal_event_both_respected():
    """Lunch block + a GCal meeting on the same day — both carved out correctly."""
    tuesday = date(2026, 4, 7)
    # Flamingo meeting 15:00–16:00, buffer 15min each side → blocks 14:45–16:15
    meeting = make_event("Afternoon sync", 15, 0, 16, 0, color_id="4", target_date=tuesday)
    windows = compute_free_windows([meeting], tuesday, DAILY_BLOCKS_CONTEXT)

    lunch_start = datetime(2026, 4, 7, 13, 0, tzinfo=TZ)
    lunch_end = datetime(2026, 4, 7, 14, 0, tzinfo=TZ)
    meeting_buf_start = datetime(2026, 4, 7, 14, 45, tzinfo=TZ)
    meeting_buf_end = datetime(2026, 4, 7, 16, 15, tzinfo=TZ)

    for w in windows:
        assert not (w.start < lunch_end and w.end > lunch_start), (
            f"Window overlaps Lunch: {w.start}–{w.end}"
        )
        assert not (w.start < meeting_buf_end and w.end > meeting_buf_start), (
            f"Window overlaps meeting buffer: {w.start}–{w.end}"
        )

    # Window after meeting buffer must start at 16:15
    after_meeting = [w for w in windows if w.start >= meeting_buf_end]
    assert after_meeting, "Expected a window after the meeting buffer"
    assert _hm(after_meeting[0].start) == (16, 15)
