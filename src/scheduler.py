"""
Free window calculator — pure logic, no external API calls.

Algorithm:
1. Determine effective day start: wake + buffer, clamped by first_task_not_before
   and weekend rule. Late-night-prior adds 90min penalty.
2. Day ends at no_tasks_after (default 23:00).
3. Build blocked intervals: morning block + per-event blocks with color-based buffers.
4. Merge overlapping blocked intervals.
5. Find free gaps between merged intervals within [effective_start, day_end].
6. Tag each gap with a descriptive block_type.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.models import CalendarEvent, FreeWindow

_TIMEZONE_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def _normalize_tz(tz_str: str) -> str:
    return _TIMEZONE_ALIASES.get(tz_str, tz_str)


def _parse_time(time_str: str, target_date: date, tz: ZoneInfo) -> datetime:
    """Parse 'HH:MM' into a timezone-aware datetime on target_date."""
    h, m = map(int, time_str.split(":"))
    return datetime(target_date.year, target_date.month, target_date.day, h, m, 0, tzinfo=tz)


def _get_event_buffers(event: CalendarEvent, context: dict) -> tuple[int, int]:
    """Return (buffer_before_minutes, buffer_after_minutes) for an event based on colorId."""
    for rule in context.get("calendar_rules", {}).values():
        if rule.get("color_id") == event.color_id:
            return rule.get("buffer_before_minutes", 0), rule.get("buffer_after_minutes", 0)
    return 0, 0


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Merge a list of possibly-overlapping (start, end) intervals."""
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _block_type(start: datetime) -> str:
    hour = start.hour
    if hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    return "evening"


def compute_free_windows(
    events: list[CalendarEvent],
    target_date: date,
    context: dict,
    late_night_prior: bool = False,
) -> list[FreeWindow]:
    """
    Compute schedulable free windows for target_date.

    Args:
        events:           Calendar events for target_date (may include all-day).
        target_date:      The date to compute windows for.
        context:          Parsed context.json dict.
        late_night_prior: True if previous day had an event ending after 23:00.

    Returns:
        Sorted list of FreeWindow objects.
    """
    tz_str = _normalize_tz(context.get("user", {}).get("timezone", "America/Vancouver"))
    tz = ZoneInfo(tz_str)

    sleep = context.get("sleep", {})
    wake_str = sleep.get("default_wake_time", "09:00")
    buffer_mins: int = sleep.get("morning_buffer_minutes", 90)
    first_task_str = sleep.get("first_task_not_before", "10:30")
    no_tasks_after_str = sleep.get("no_tasks_after", "23:00")
    weekend_days = {d.lower() for d in sleep.get("weekend_days", ["friday", "saturday", "sunday"])}
    weekend_start_str = sleep.get("weekend_nothing_before", "13:00")

    wake_dt = _parse_time(wake_str, target_date, tz)

    if late_night_prior:
        # Shift wake time forward 90 minutes to account for late night
        wake_dt += timedelta(minutes=90)

    effective_start = wake_dt + timedelta(minutes=buffer_mins)

    # Hard minimum: first_task_not_before
    effective_start = max(effective_start, _parse_time(first_task_str, target_date, tz))

    # Weekend rule: nothing before weekend_nothing_before, no exceptions
    day_name = target_date.strftime("%A").lower()
    if day_name in weekend_days:
        effective_start = max(effective_start, _parse_time(weekend_start_str, target_date, tz))

    day_end = _parse_time(no_tasks_after_str, target_date, tz)

    if effective_start >= day_end:
        return []

    midnight = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz)
    end_of_day = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=tz)

    # Build blocked intervals
    blocked: list[tuple[datetime, datetime]] = []

    # Morning is unavailable until effective_start
    if effective_start > midnight:
        blocked.append((midnight, effective_start))

    # After no_tasks_after until end of day
    if day_end < end_of_day:
        blocked.append((day_end, end_of_day))

    # Calendar events (skip all-day — they don't occupy clock time)
    for event in events:
        if event.is_all_day:
            continue
        buf_before, buf_after = _get_event_buffers(event, context)
        block_start = max(event.start - timedelta(minutes=buf_before), midnight)
        block_end = min(event.end + timedelta(minutes=buf_after), end_of_day)
        if block_start < block_end:
            blocked.append((block_start, block_end))

    merged = _merge_intervals(blocked)

    # Find gaps between merged blocked intervals
    free_windows: list[FreeWindow] = []
    cursor = midnight

    for block_start, block_end in merged:
        gap_start = max(cursor, effective_start)
        gap_end = min(block_start, day_end)

        if gap_start < gap_end:
            duration = int((gap_end - gap_start).total_seconds() / 60)
            if duration > 0:
                free_windows.append(FreeWindow(
                    start=gap_start,
                    end=gap_end,
                    duration_minutes=duration,
                    block_type=_block_type(gap_start),
                ))

        cursor = block_end

    # Gap after the last blocked interval
    gap_start = max(cursor, effective_start)
    gap_end = day_end
    if gap_start < gap_end:
        duration = int((gap_end - gap_start).total_seconds() / 60)
        if duration > 0:
            free_windows.append(FreeWindow(
                start=gap_start,
                end=gap_end,
                duration_minutes=duration,
                block_type=_block_type(gap_start),
            ))

    return free_windows
