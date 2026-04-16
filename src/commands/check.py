"""--check command: validate the full data pipeline without calling the LLM."""

import os
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from src.calendar_client import get_events
from src.db import setup_database
from src.scheduler import compute_free_windows
from src.todoist_client import TodoistClient

_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def _late_night_threshold_dt(base_date: date, context: dict, tz: ZoneInfo):
    """Return the late-night threshold as a timezone-aware datetime."""
    from datetime import datetime
    from src.scheduler import _parse_hm
    threshold_str = context.get("sleep", {}).get("late_night_threshold", "23:00")
    next_day = "next day" in threshold_str
    hm = threshold_str.replace("next day", "").strip()
    h, m = _parse_hm(hm)
    ref = base_date + timedelta(days=1) if next_day else base_date
    return datetime(ref.year, ref.month, ref.day, h, m, tzinfo=tz)


def cmd_check(context: dict) -> None:
    """--check: validate data pipeline end-to-end without calling the LLM."""
    setup_database()
    print("[DB] Database ready at data/schedule.db")

    today = date.today()
    yesterday = today - timedelta(days=1)
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _TZ_ALIASES.get(tz_str, tz_str)

    # ── Google Calendar ───────────────────────────────────────────────────────
    print(f"\n[GCal] Fetching events for {today}...")
    events = []
    try:
        extra_cal_ids = context.get("calendar_ids", [])
        events = get_events(today, tz_str, extra_calendar_ids=extra_cal_ids)
        if events:
            for e in events:
                time_str = (
                    "[all-day]"
                    if e.is_all_day
                    else f"{e.start.strftime('%H:%M')}–{e.end.strftime('%H:%M')}"
                )
                color_str = f" [colorId={e.color_id}]" if e.color_id else ""
                print(f"       {time_str}  {e.summary}{color_str}")
        else:
            print("       (no events)")
    except Exception as exc:
        print(f"[WARN] GCal fetch failed: {exc}")

    # ── Late night detection ──────────────────────────────────────────────────
    late_night_prior = False
    try:
        tz = ZoneInfo(tz_str_norm)
        threshold_dt = _late_night_threshold_dt(yesterday, context, tz)
        yesterday_events = get_events(
            yesterday, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        )
        for ev in yesterday_events:
            ev_end = ev.end if ev.end.tzinfo else ev.end.replace(tzinfo=tz)
            if not ev.is_all_day and ev_end >= threshold_dt:
                late_night_prior = True
                print(
                    f"[GCal] Late night detected: '{ev.summary}' ended at "
                    f"{ev.end.strftime('%H:%M')} — morning buffer extended"
                )
                break
    except Exception:
        pass

    # ── Todoist ───────────────────────────────────────────────────────────────
    print(f"\n[Todoist] Fetching tasks (filter: '!date | today | overdue')...")
    tasks = []
    try:
        client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))
        tasks = client.get_tasks("!date | today | overdue")
        if tasks:
            priority_label = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
            for t in tasks:
                p = priority_label.get(t.priority, "P?")
                dur = f" ({t.duration_minutes}min)" if t.duration_minutes else ""
                labels = f" [{', '.join(t.labels)}]" if t.labels else ""
                inbox = " [inbox]" if t.is_inbox else ""
                print(f"       [{p}] {t.content}{dur}{labels}{inbox}")
        else:
            print("       (no tasks)")
    except Exception as exc:
        print(f"[WARN] Todoist fetch failed: {exc}")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    print(f"\n[Scheduler] Computing free windows for {today}...")
    windows = []
    try:
        windows = compute_free_windows(
            events, today, context, late_night_prior=late_night_prior
        )
        if windows:
            for w in windows:
                print(
                    f"       {w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')} "
                    f"({w.duration_minutes}min) [{w.block_type}]"
                )
        else:
            print("       (no free windows — fully blocked day)")
    except Exception as exc:
        print(f"[WARN] Scheduler failed: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(
        f"\n{'─'*55}\n"
        f"  {len(events)} calendar event(s) today  |  "
        f"{len(tasks)} task(s) in Todoist  |  "
        f"{len(windows)} free window(s) computed\n"
        f"{'─'*55}"
    )
