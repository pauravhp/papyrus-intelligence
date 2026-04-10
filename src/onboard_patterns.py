"""
Pure pattern detection from calendar events for --onboard Stage 1.
No API calls, no I/O — just computation over CalendarEvent objects.
"""

from collections import Counter, defaultdict
from datetime import date

from src.models import CalendarEvent

_DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MEETING_KEYWORDS = {
    "meeting", "call", "sync", "standup", "stand-up", "interview",
    "chat", "zoom", "teams", "google meet", "1:1", "catchup",
}
_EVENT_KEYWORDS = {
    "dinner", "lunch", "party", "event", "class", "gym",
    "appointment", "coffee", "brunch", "breakfast",
}


def detect_wake_times(events_by_date: dict[date, list[CalendarEvent]]) -> dict:
    """
    Per day of week, find the median earliest non-all-day event start time.
    Proxy for active hours — actual wake time is inferred by the LLM with a buffer.
    """
    day_earliest: dict[str, list[int]] = defaultdict(list)

    for d, events in events_by_date.items():
        day_name = _DAYS_OF_WEEK[d.weekday()]
        non_allday = [e for e in events if not e.is_all_day]
        if non_allday:
            earliest = min(non_allday, key=lambda e: e.start)
            minutes = earliest.start.hour * 60 + earliest.start.minute
            day_earliest[day_name].append(minutes)

    per_day: dict[str, str | None] = {}
    for day in _DAYS_OF_WEEK:
        times = sorted(day_earliest.get(day, []))
        if times:
            med = times[len(times) // 2]
            h, m = divmod(med, 60)
            per_day[day] = f"{h:02d}:{m:02d}"
        else:
            per_day[day] = None

    weekday_times = [per_day[d] for d in _DAYS_OF_WEEK[:5] if per_day[d]]
    weekend_times = [per_day[d] for d in _DAYS_OF_WEEK[5:] if per_day[d]]
    days_with_data = sum(1 for v in per_day.values() if v is not None)

    return {
        "per_day_of_week": per_day,
        "weekday_summary": (
            f"Earliest events typically around {min(weekday_times)}"
            if weekday_times else "No weekday events detected"
        ),
        "weekend_summary": (
            f"Earliest events typically around {min(weekend_times)}"
            if weekend_times else "No weekend events — likely free mornings"
        ),
        "days_with_data": days_with_data,
    }


def detect_color_semantics(all_events: list[CalendarEvent]) -> dict:
    """
    Group non-all-day events by colorId. Summarize count, average duration, and top names.
    Infers likely event type (meeting_or_call, personal_event, focus_block, unknown).
    """
    by_color: dict[str, list[dict]] = defaultdict(list)

    for e in all_events:
        if e.is_all_day:
            continue
        color = e.color_id or "none"
        duration = int((e.end - e.start).total_seconds() / 60)
        by_color[color].append({"name": e.summary, "duration_min": duration})

    result: dict[str, dict] = {}
    for color, entries in sorted(by_color.items()):
        names = [e["name"] for e in entries]
        durations = [e["duration_min"] for e in entries]
        avg_dur = sum(durations) / len(durations)
        top = _top_names(names, 5)
        result[color] = {
            "count": len(entries),
            "avg_duration_min": round(avg_dur),
            "top_names": top,
            "likely_type": _infer_event_type(avg_dur, top),
        }

    return result


def detect_recurring_blocks(all_events: list[CalendarEvent]) -> list[dict]:
    """
    Find events with the same name appearing at similar times on the same day of week.
    2+ occurrences in the scan window = likely recurring.
    """
    # Key: (lowercase_name, day_of_week, hour_bucket)
    groups: dict[tuple, list[CalendarEvent]] = defaultdict(list)

    for e in all_events:
        if e.is_all_day:
            continue
        name_key = e.summary.lower().strip()
        day_key = _DAYS_OF_WEEK[e.start.weekday()]
        hour_key = e.start.hour
        groups[(name_key, day_key, hour_key)].append(e)

    recurring: list[dict] = []
    for (_, day, hour), events in groups.items():
        if len(events) >= 2:
            sample = events[0]
            duration = int((sample.end - sample.start).total_seconds() / 60)
            recurring.append({
                "name": sample.summary,
                "day_of_week": day,
                "time": f"{hour:02d}:00",
                "occurrences_in_scan_window": len(events),
                "duration_min": duration,
            })

    recurring.sort(key=lambda x: x["occurrences_in_scan_window"], reverse=True)
    return recurring


def detect_sleep_signals(events_by_date: dict[date, list[CalendarEvent]]) -> dict:
    """
    Detect late-night activity by finding the latest event end per day.
    High latest-end times → likely late sleep schedule.
    """
    late_events: list[dict] = []
    latest_per_day: dict[str, list[int]] = defaultdict(list)

    for d, events in events_by_date.items():
        day_name = _DAYS_OF_WEEK[d.weekday()]
        non_allday = [e for e in events if not e.is_all_day]
        if non_allday:
            latest = max(non_allday, key=lambda e: e.end)
            end_min = latest.end.hour * 60 + latest.end.minute
            latest_per_day[day_name].append(end_min)
            if latest.end.hour >= 22:
                late_events.append({
                    "name": latest.summary,
                    "end_time": f"{latest.end.hour:02d}:{latest.end.minute:02d}",
                    "date": str(d),
                    "day_of_week": day_name,
                })

    per_day: dict[str, str | None] = {}
    for day in _DAYS_OF_WEEK:
        times = sorted(latest_per_day.get(day, []))
        if times:
            med = times[len(times) // 2]
            h, m = divmod(med, 60)
            per_day[day] = f"{h:02d}:{m:02d}"
        else:
            per_day[day] = None

    return {
        "median_latest_event_per_day": per_day,
        "late_night_events_after_10pm": late_events[:5],
        "late_night_count": len(late_events),
    }


def build_pattern_summary(
    events_by_date: dict[date, list[CalendarEvent]],
    all_events: list[CalendarEvent],
) -> dict:
    """Aggregate all pattern detectors into a single summary dict for the LLM."""
    return {
        "wake_times": detect_wake_times(events_by_date),
        "color_semantics": detect_color_semantics(all_events),
        "recurring_blocks": detect_recurring_blocks(all_events),
        "sleep_signals": detect_sleep_signals(events_by_date),
        "total_events_scanned": len(all_events),
        "days_with_events": sum(1 for evts in events_by_date.values() if evts),
        "scan_window_days": len(events_by_date),
    }


def _top_names(names: list[str], n: int) -> list[str]:
    return [name for name, _ in Counter(names).most_common(n)]


def _infer_event_type(avg_duration: float, top_names: list[str]) -> str:
    name_text = " ".join(top_names).lower()
    if any(k in name_text for k in _MEETING_KEYWORDS):
        return "meeting_or_call"
    if any(k in name_text for k in _EVENT_KEYWORDS):
        return "personal_event"
    if avg_duration <= 60:
        return "likely_meeting"
    if avg_duration >= 120:
        return "likely_focus_block_or_event"
    return "unknown"
