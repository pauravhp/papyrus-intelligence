"""
Free window calculator — pure logic, no external API calls.

Algorithm:
1. Determine effective day start: wake + buffer, clamped by first_task_not_before
   and weekend rule. Late-night-prior adds 90min penalty.
2. Day ends at no_tasks_after (default 23:00).
3. Build blocked intervals from four sources, all treated identically:
   a. Morning buffer block
   b. GCal events with color-based buffers
   c. daily_blocks from context.json (meals, personal fixed blocks)
   d. Already-scheduled Todoist tasks (due_datetime on target_date)
4. Merge overlapping blocked intervals.
5. Find free gaps between merged intervals within [effective_start, day_end].
6. Tag each gap with a descriptive block_type.

Windows are returned as raw continuous blocks — NOT pre-chunked.
pack_schedule() owns all break insertion and ultradian cycle enforcement.
"""

from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from src.models import CalendarEvent, FreeWindow, ScheduledBlock, TodoistTask

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


def _parse_time_extended(time_str: str, target_date: date, tz: ZoneInfo) -> datetime:
    """Parse 'HH:MM' or 'HH:MM next day' into a timezone-aware datetime.

    'next day' means the time falls on target_date + 1 — used for windows
    that extend past midnight (e.g. no_tasks_after: '00:30 next day').
    """
    next_day = "next day" in time_str
    hm = time_str.replace("next day", "").strip()
    h, m = map(int, hm.split(":"))
    base = target_date + timedelta(days=1) if next_day else target_date
    return datetime(base.year, base.month, base.day, h, m, 0, tzinfo=tz)


def _applies_on_day(days_spec, day_name: str) -> bool:
    """Return True if a daily_block's 'days' field covers the given day.

    days_spec values:
      "all"      → every day
      "weekdays" → Mon–Fri
      "weekends" → Sat–Sun (standard definition, independent of user's weekend_days)
      list       → e.g. ["monday", "friday"]
    """
    if days_spec == "all":
        return True
    if days_spec == "weekdays":
        return day_name in {"monday", "tuesday", "wednesday", "thursday", "friday"}
    if days_spec == "weekends":
        return day_name in {"saturday", "sunday"}
    if isinstance(days_spec, list):
        return day_name in {d.lower() for d in days_spec}
    return False


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
    if hour < 6:
        return "late night"
    elif hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    elif hour < 22:
        return "evening"
    return "late night"


def compute_free_windows(
    events: list[CalendarEvent],
    target_date: date,
    context: dict,
    late_night_prior: bool = False,
    scheduled_tasks: Optional[list[TodoistTask]] = None,
    start_override: Optional[datetime] = None,
    now_override: Optional[datetime] = None,
) -> list[FreeWindow]:
    """
    Compute schedulable free windows for target_date.

    Args:
        events:           Calendar events for target_date (may include all-day).
        target_date:      The date to compute windows for.
        context:          Parsed context.json dict.
        late_night_prior: True if previous day had an event ending after 23:00.
        scheduled_tasks:  Todoist tasks already given a due_datetime on target_date.
                          Their occupied time is blocked identically to GCal events
                          (no color-based buffers) to prevent double-booking.
        start_override:   When provided, skip all wake/buffer/weekend calculations
                          and use this datetime directly as effective_start.
                          Used by --add-task to replan from the current time.
        now_override:     When provided, used as "current time" for mid-day detection
                          instead of datetime.now(). Useful for testing.

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

    # Mid-day check: if planning for today and the current time has already passed the
    # computed morning start, advance effective_start to now (ceiled to next 5-min boundary).
    # Only applies when start_override is not set — --add-task uses start_override directly.
    if start_override is None and target_date == date.today():
        effective_now = (
            now_override if now_override is not None else datetime.now(tz=tz)
        )
        if effective_now.tzinfo is None:
            effective_now = effective_now.replace(tzinfo=tz)
        else:
            effective_now = effective_now.astimezone(tz)
        if effective_now > effective_start:
            extra = (5 - effective_now.minute % 5) % 5
            if extra == 0 and (effective_now.second > 0 or effective_now.microsecond > 0):
                extra = 5
            effective_start = (effective_now + timedelta(minutes=extra)).replace(
                second=0, microsecond=0
            )

    # When replanning mid-day, skip morning rules and start from now
    if start_override is not None:
        effective_start = start_override

    # Supports "HH:MM next day" for windows that extend past midnight
    day_end = _parse_time_extended(no_tasks_after_str, target_date, tz)

    if effective_start >= day_end:
        return []

    midnight = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz)
    # end_of_day == day_end so tasks are naturally clipped at the cutoff
    end_of_day = day_end

    # Build blocked intervals
    blocked: list[tuple[datetime, datetime]] = []

    # Morning is unavailable until effective_start
    if effective_start > midnight:
        blocked.append((midnight, effective_start))

    # Calendar events (skip all-day — they don't occupy clock time)
    for event in events:
        if event.is_all_day:
            continue
        buf_before, buf_after = _get_event_buffers(event, context)
        block_start = max(event.start - timedelta(minutes=buf_before), midnight)
        block_end = min(event.end + timedelta(minutes=buf_after), end_of_day)
        if block_start < block_end:
            blocked.append((block_start, block_end))

    # daily_blocks from context.json (meals, personal fixed blocks)
    for db in context.get("daily_blocks", []):
        if not _applies_on_day(db.get("days", "all"), day_name):
            continue
        buf_before = db.get("buffer_before_minutes", 0)
        buf_after = db.get("buffer_after_minutes", 0)
        block_start = max(_parse_time(db["start"], target_date, tz) - timedelta(minutes=buf_before), midnight)
        block_end = min(_parse_time(db["end"], target_date, tz) + timedelta(minutes=buf_after), end_of_day)
        if block_start < block_end:
            blocked.append((block_start, block_end))

    # Already-scheduled Todoist tasks — block their time to prevent double-booking
    if scheduled_tasks:
        for task in scheduled_tasks:
            if task.due_datetime is None or task.duration_minutes is None:
                continue
            # Normalize to local tz if aware, or treat as local if naive
            task_start = task.due_datetime
            if task_start.tzinfo is None:
                task_start = task_start.replace(tzinfo=tz)
            else:
                task_start = task_start.astimezone(tz)
            # Only block if this task is on target_date
            if task_start.date() != target_date:
                continue
            task_end = task_start + timedelta(minutes=task.duration_minutes)
            block_start = max(task_start, midnight)
            block_end = min(task_end, end_of_day)
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

    # Peak window: first_task_not_before → first_task_not_before + 5h
    sleep_cfg = context.get("sleep", {})
    first_task_str = sleep_cfg.get("first_task_not_before", "10:30")
    try:
        _fh, _fm = map(int, first_task_str.split(":"))
    except (ValueError, AttributeError):
        _fh, _fm = 10, 30
    _peak_end_hour = _fh + 5  # e.g. 10 + 5 = 15 (3pm)

    blocks: list[ScheduledBlock] = []
    auto_pushed: list[dict] = []

    # Mutable cursor state (captured by the nested helper via nonlocal)
    window_idx = 0
    cursor = free_windows[0].start
    continuous_minutes = 0

    # dw_ln_cursor tracks how much of the late-night window has been consumed by
    # DW tasks placed "out-of-band" (while the main cursor was still in afternoon).
    # This allows non-DW tasks to keep using the afternoon window after a DW task
    # is placed in late night, instead of abandoning the remaining afternoon time.
    dw_ln_cursor: datetime | None = None

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

        # If we've entered a late-night window, skip past any portion already
        # consumed by out-of-band DW task placements.
        _in_ln = cursor.hour >= 22 or cursor.hour < 6
        if _in_ln and dw_ln_cursor is not None and cursor < dw_ln_cursor:
            cursor = dw_ln_cursor
            if cursor >= free_windows[window_idx].end:
                window_idx += 1
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

        # @deep-work enforcement: allow peak window (10:30–peak_end) OR late night (22:00+)
        # Forbidden zone (peak_end–22:00): route out-of-band to late night.
        # Morning peak but task doesn't fit current window: also route out-of-band so the
        # current window stays available for shorter tasks that follow.
        if "needs-deep-work-block" in flags:
            in_late_night = cursor.hour >= 22 or cursor.hour < 6
            in_forbidden = cursor.hour >= _peak_end_hour and not in_late_night
            in_morning_no_fit = cursor.hour < _peak_end_hour and duration > remaining
            if in_forbidden or in_morning_no_fit:
                # Find the late-night window (search all windows, not just from window_idx)
                ln_window = None
                for w in free_windows:
                    if w.start.hour >= 22 or w.start.hour < 6:
                        ln_window = w
                        break
                if ln_window is None:
                    auto_pushed.append({
                        "task_id": task_id,
                        "task_name": task_name,
                        "reason": "@deep-work task — no peak or late-night window available today",
                        "suggested_date": tomorrow,
                    })
                    continue

                # Place after any previously out-of-band DW tasks
                dw_start = dw_ln_cursor if dw_ln_cursor is not None else ln_window.start
                dw_avail = int((ln_window.end - dw_start).total_seconds() / 60)
                if duration > dw_avail:
                    auto_pushed.append({
                        "task_id": task_id,
                        "task_name": task_name,
                        "reason": "@deep-work task — no peak or late-night window available today",
                        "suggested_date": tomorrow,
                    })
                    continue

                dw_end = dw_start + timedelta(minutes=duration)
                blocks.append(ScheduledBlock(
                    task_id=task_id,
                    task_name=task_name,
                    start_time=dw_start,
                    end_time=dw_end,
                    duration_minutes=duration,
                    work_block=block_label,
                    placement_reason=placement_reason,
                ))
                dw_ln_cursor = dw_end
                # Main cursor and window_idx intentionally NOT updated — non-DW tasks
                # continue scheduling from the current morning/afternoon position.
                continue

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
                # Skip past out-of-band DW placements already in the late-night window
                _in_ln2 = part2_start.hour >= 22 or part2_start.hour < 6
                if _in_ln2 and dw_ln_cursor is not None and part2_start < dw_ln_cursor:
                    part2_start = dw_ln_cursor
                    cursor = dw_ln_cursor

                if part2_start >= free_windows[window_idx].end:
                    # Late-night window fully consumed by DW tasks; push remainder
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
            # ── Task doesn't fit and can't split: search later windows ───────
            # Cursor stays at current position — current window remains available
            # for subsequent shorter tasks.
            placed = False
            for look_idx in range(window_idx + 1, len(free_windows)):
                look_window = free_windows[look_idx]
                # Skip past out-of-band DW placements in late-night windows
                look_start = look_window.start
                _in_ln_look = look_start.hour >= 22 or look_start.hour < 6
                if _in_ln_look and dw_ln_cursor is not None and look_start < dw_ln_cursor:
                    look_start = dw_ln_cursor
                if look_start >= look_window.end:
                    continue  # window fully consumed by DW tasks
                look_avail = int((look_window.end - look_start).total_seconds() / 60)
                if duration <= look_avail:
                    end_time = look_start + timedelta(minutes=duration)
                    blocks.append(ScheduledBlock(
                        task_id=task_id,
                        task_name=task_name,
                        start_time=look_start,
                        end_time=end_time,
                        duration_minutes=duration,
                        work_block=block_label,
                        placement_reason=placement_reason,
                    ))
                    cursor = end_time
                    window_idx = look_idx
                    continuous_minutes = duration
                    placed = True
                    break

            if not placed:
                auto_pushed.append({
                    "task_id": task_id,
                    "task_name": task_name,
                    "reason": (
                        f"Needs {duration}min — doesn't fit in any remaining window today"
                    ),
                    "suggested_date": tomorrow,
                })

        # Apply any explicit post-task break preference
        if break_after > 0:
            cursor += timedelta(minutes=break_after)
            continuous_minutes = 0

    # Post-process: compute back_to_back for each placed block.
    # Sort chronologically (handles out-of-band DW late-night placements correctly),
    # then flag any block whose start is within 10 min of the previous block's end.
    if blocks:
        blocks_sorted = sorted(blocks, key=lambda b: b.start_time)
        blocks_sorted[0].back_to_back = False
        for i in range(1, len(blocks_sorted)):
            prev = blocks_sorted[i - 1]
            curr = blocks_sorted[i]
            gap_mins = int((curr.start_time - prev.end_time).total_seconds() / 60)
            curr.back_to_back = 0 <= gap_mins < 10

    return blocks, auto_pushed
