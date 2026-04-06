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

Windows are returned as raw continuous blocks — NOT pre-chunked.
pack_schedule() owns all break insertion and ultradian cycle enforcement.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.models import CalendarEvent, FreeWindow, ScheduledBlock

# A single schedulable block should not exceed one ultradian cycle (90 min per BRAC).
# Longer uninterrupted stretches are split with a mandatory break so the scheduler
# reflects realistic human capacity rather than handing the LLM a 10-hour open canvas.
MAX_WINDOW_MINUTES = 90
BREAK_BETWEEN_WINDOWS_MINUTES = 15

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


# ── pack_schedule ───────────────────────────────────────────────────────────────

_MIN_SPLIT_MINUTES = 30  # minimum chunk size to bother splitting a task


def pack_schedule(
    ordered_tasks: list[dict],
    free_windows: list[FreeWindow],
    context: dict,
    target_date: date | None = None,
) -> tuple[list[ScheduledBlock], list[dict]]:
    """
    Cursor-based time assignment. The LLM defines task order; this function
    handles all clock math: slot finding, forced ultradian breaks, and splits.

    Args:
        ordered_tasks:  LLM-ordered task dicts with duration_minutes, can_be_split,
                        break_after_minutes, block_label, placement_reason,
                        scheduling_flags.
        free_windows:   Pre-computed schedulable windows (from compute_free_windows).
        context:        Parsed context.json dict (not currently used but kept for
                        future constraint injection).
        target_date:    Date being scheduled (defaults to today; injectable for tests).

    Returns:
        (scheduled_blocks, auto_pushed) — blocks placed on the calendar and tasks
        that couldn't fit and were pushed to the next day.
    """
    if not ordered_tasks or not free_windows:
        return [], []

    _target = target_date or date.today()
    tomorrow = (_target + timedelta(days=1)).isoformat()

    blocks: list[ScheduledBlock] = []
    auto_pushed: list[dict] = []

    # Mutable cursor state (captured by the nested helper via nonlocal)
    window_idx = 0
    cursor = free_windows[0].start
    continuous_minutes = 0

    def _advance() -> bool:
        """Advance cursor and window_idx to the next schedulable position.
        Moves cursor to the window's start if it's still before it.
        Returns False when no windows remain."""
        nonlocal cursor, window_idx
        while window_idx < len(free_windows):
            w = free_windows[window_idx]
            if cursor <= w.start:
                cursor = w.start
                return True
            if cursor < w.end:
                return True
            window_idx += 1
        return False

    for task in ordered_tasks:
        task_id = task.get("task_id", "")
        task_name = task.get("task_name", task.get("content", ""))
        duration = task.get("duration_minutes") or 30
        can_be_split = task.get("can_be_split", False)
        break_after = task.get("break_after_minutes") or 0
        block_label = task.get("block_label", "")
        placement_reason = task.get("placement_reason", "")
        flags = task.get("scheduling_flags", [])

        # @waiting and similar tasks are never auto-scheduled
        if "never-schedule" in flags:
            auto_pushed.append({
                "task_id": task_id,
                "task_name": task_name,
                "reason": "@waiting — never auto-scheduled",
                "suggested_date": "",
            })
            continue

        # Enforce ultradian break if continuous work hit the cap
        if continuous_minutes >= MAX_WINDOW_MINUTES:
            cursor += timedelta(minutes=BREAK_BETWEEN_WINDOWS_MINUTES)
            continuous_minutes = 0

        # Find a valid slot
        if not _advance():
            auto_pushed.append({
                "task_id": task_id,
                "task_name": task_name,
                "reason": "No more free windows today",
                "suggested_date": tomorrow,
            })
            continue

        current_window = free_windows[window_idx]
        remaining = int((current_window.end - cursor).total_seconds() / 60)

        if duration <= remaining:
            # ── Happy path: task fits in the current window ──────────────────
            end_time = cursor + timedelta(minutes=duration)
            blocks.append(ScheduledBlock(
                task_id=task_id,
                task_name=task_name,
                start_time=cursor,
                end_time=end_time,
                duration_minutes=duration,
                work_block=block_label,
                placement_reason=placement_reason,
            ))
            cursor = end_time
            continuous_minutes += duration

        elif can_be_split and remaining >= _MIN_SPLIT_MINUTES:
            # ── Split: part 1 fills current window, part 2 goes to next ─────
            part1_dur = remaining
            part2_dur = duration - part1_dur
            part1_end = current_window.end

            blocks.append(ScheduledBlock(
                task_id=task_id,
                task_name=task_name,
                start_time=cursor,
                end_time=part1_end,
                duration_minutes=part1_dur,
                work_block=block_label,
                placement_reason=placement_reason,
                split_session=True,
                split_part=1,
            ))
            continuous_minutes += part1_dur

            # Move past this window; the gap between windows is the break
            cursor = part1_end
            window_idx += 1
            continuous_minutes = 0

            if _advance():
                part2_start = cursor
                part2_end = part2_start + timedelta(minutes=part2_dur)
                # Clip to window boundary if necessary
                if part2_end > free_windows[window_idx].end:
                    part2_end = free_windows[window_idx].end
                    part2_dur = int((part2_end - part2_start).total_seconds() / 60)

                blocks.append(ScheduledBlock(
                    task_id=task_id,
                    task_name=task_name,
                    start_time=part2_start,
                    end_time=part2_end,
                    duration_minutes=part2_dur,
                    work_block=block_label,
                    placement_reason="Continuation from earlier session",
                    split_session=True,
                    split_part=2,
                ))
                cursor = part2_end
                continuous_minutes = part2_dur
            else:
                auto_pushed.append({
                    "task_id": task_id,
                    "task_name": task_name + " (remainder)",
                    "reason": (
                        f"First {part1_dur}min session scheduled; "
                        f"{part2_dur}min remainder has no window today"
                    ),
                    "suggested_date": tomorrow,
                })

        else:
            # ── Task doesn't fit and can't split: try the next window ────────
            cursor = current_window.end
            window_idx += 1
            continuous_minutes = 0

            if _advance():
                next_window = free_windows[window_idx]
                next_remaining = int((next_window.end - cursor).total_seconds() / 60)
                if duration <= next_remaining:
                    end_time = cursor + timedelta(minutes=duration)
                    blocks.append(ScheduledBlock(
                        task_id=task_id,
                        task_name=task_name,
                        start_time=cursor,
                        end_time=end_time,
                        duration_minutes=duration,
                        work_block=block_label,
                        placement_reason=placement_reason,
                    ))
                    cursor = end_time
                    continuous_minutes = duration
                else:
                    auto_pushed.append({
                        "task_id": task_id,
                        "task_name": task_name,
                        "reason": (
                            f"Needs {duration}min — doesn't fit in any remaining window today"
                        ),
                        "suggested_date": tomorrow,
                    })
            else:
                auto_pushed.append({
                    "task_id": task_id,
                    "task_name": task_name,
                    "reason": "No more free windows today",
                    "suggested_date": tomorrow,
                })

        # Apply any explicit post-task break preference
        if break_after > 0:
            cursor += timedelta(minutes=break_after)
            continuous_minutes = 0

    return blocks, auto_pushed
