#!/usr/bin/env python3
"""
Scheduling Agent — CLI entry point.

Usage:
  python main.py --check        Validate the full data pipeline (no LLM)
  python main.py --plan-day     Run full scheduling pipeline (Phase 1+)
  python main.py --review       Review pushed/flagged tasks (Phase 2+)
  python main.py --add-task     Add a task to Todoist inbox
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Model names mirrored here for display in progress messages
ENRICH_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
SCHEDULE_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _late_night_threshold_dt(base_date: date, context: dict, tz: ZoneInfo) -> datetime:
    """Return the late-night threshold as a timezone-aware datetime.

    base_date is the day being checked (e.g. yesterday).
    'HH:MM next day' means the time falls on base_date + 1 day.
    Defaults to 23:00 on base_date if not configured.
    """
    threshold_str = context.get("sleep", {}).get("late_night_threshold", "23:00")
    next_day = "next day" in threshold_str
    hm = threshold_str.replace("next day", "").strip()
    h, m = map(int, hm.split(":"))
    ref = base_date + timedelta(days=1) if next_day else base_date
    return datetime(ref.year, ref.month, ref.day, h, m, tzinfo=tz)


def _load_config() -> dict:
    """Load .env and context.json. Exit immediately if anything is missing."""
    load_dotenv()

    required_vars = ["TODOIST_API_TOKEN", "GROQ_API_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"[ERROR] Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    context_path = Path(__file__).parent / "context.json"
    if not context_path.exists():
        print("[ERROR] context.json not found in project root")
        sys.exit(1)

    with open(context_path) as f:
        context = json.load(f)

    return context


def _cmd_check(context: dict) -> None:
    """--check: validate data pipeline end-to-end without calling the LLM."""
    from src.calendar_client import get_events
    from src.db import setup_database
    from src.scheduler import compute_free_windows
    from src.todoist_client import TodoistClient

    # ── Database ──────────────────────────────────────────────────────────────
    setup_database()
    print("[DB] Database ready at data/schedule.db")

    today = date.today()
    yesterday = today - timedelta(days=1)
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")

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

    # ── Late night detection (check yesterday's events) ───────────────────────
    late_night_prior = False
    try:
        tz = ZoneInfo(tz_str)
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
        pass  # Non-fatal: yesterday fetch is best-effort

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


_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
_PRIORITY_API = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}  # display label → Todoist API int
_WIDTH = 57


def _display_schedule(
    blocks: list,
    pushed: list[dict],
    flagged: list[dict],
    reasoning_summary: str,
    task_map: dict,
    today: date,
    already_scheduled: list | None = None,
) -> None:
    """Pretty-print the final schedule (ScheduledBlock objects) to the terminal."""
    from src.models import ScheduledBlock

    date_str = today.strftime("%A %b %d, %Y")

    print(f"\n{'═' * _WIDTH}")
    print(f"  PROPOSED SCHEDULE — {date_str}")
    print(f"{'═' * _WIDTH}")

    if reasoning_summary.strip():
        wrapped = textwrap.fill(
            reasoning_summary.strip(), width=_WIDTH - 4, subsequent_indent="     "
        )
        print(f"\n  {wrapped}")

    # ── Already Scheduled (pre-existing Todoist blocks) ───────────────────
    if already_scheduled:
        print(f"\n  {'─' * (_WIDTH - 4)}")
        print("  ALREADY SCHEDULED")
        print(f"  {'─' * (_WIDTH - 4)}")
        for t in already_scheduled:
            dt = t.due_datetime
            end_dt = dt + timedelta(minutes=t.duration_minutes)
            time_str = f"{dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"
            original = task_map.get(t.id)
            p_str = _PRIORITY_LABEL.get(original.priority, "P?") if original else "P?"
            print(f"\n  {time_str}   {t.content}  ({t.duration_minutes}min, {p_str})")

    # ── Scheduled ────────────────────────────────────────────────────────
    print(f"\n  {'─' * (_WIDTH - 4)}")
    print("  SCHEDULED")
    print(f"  {'─' * (_WIDTH - 4)}")
    if blocks:
        for block in blocks:
            time_str = (
                f"{block.start_time.strftime('%H:%M')} – "
                f"{block.end_time.strftime('%H:%M')}"
            )
            original = task_map.get(block.task_id)
            p_str = _PRIORITY_LABEL.get(original.priority, "P?") if original else "P?"

            split_tag = ""
            if block.split_session:
                # Count total parts for this task to display "part X of Y"
                total_parts = sum(
                    1 for b in blocks if b.task_id == block.task_id and b.split_session
                )
                split_tag = f" [part {block.split_part} of {total_parts}]"

            print(
                f"\n  {time_str}   {block.task_name}  "
                f"({block.duration_minutes}min, {p_str}){split_tag}"
            )
            reason = block.placement_reason.strip()
            if reason:
                wrapped_reason = textwrap.fill(
                    reason, width=_WIDTH - 8, subsequent_indent="                  "
                )
                print(f"                └─ {wrapped_reason}")
            if block.split_session and block.split_part == 1:
                print("                └─ Split — continues after break")
    else:
        print("  (nothing could be scheduled today)")

    # ── Pushed ───────────────────────────────────────────────────────────
    if pushed:
        print(f"\n  {'─' * (_WIDTH - 4)}")
        print("  PUSHED TO LATER")
        print(f"  {'─' * (_WIDTH - 4)}")
        for item in pushed:
            name = item.get("task_name", "Unknown")
            date_str_p = item.get("suggested_date", "later") or "later"
            reason = item.get("reason", "").strip()
            line = f"  •  {name} → {date_str_p}"
            if reason:
                line += f":  {reason}"
            print(textwrap.fill(line, width=_WIDTH, subsequent_indent="     "))

    # ── Flagged ──────────────────────────────────────────────────────────
    if flagged:
        print(f"\n  {'─' * (_WIDTH - 4)}")
        print("  FLAGGED")
        print(f"  {'─' * (_WIDTH - 4)}")
        for item in flagged:
            name = item.get("task_name", "Unknown")
            issue = item.get("issue", "").strip()
            print(
                textwrap.fill(
                    f"  !   {name}: {issue}", width=_WIDTH, subsequent_indent="       "
                )
            )

    print(f"\n{'═' * _WIDTH}\n")


def _parse_session_range(s: str) -> tuple[int, int]:
    """Parse '90m-180m', '90-180', '1h-3h', '90m-3h' → (min_mins, max_mins)."""

    def to_minutes(part: str) -> int:
        part = part.strip().lower()
        if part.endswith("h"):
            return int(float(part[:-1]) * 60)
        elif part.endswith("m"):
            return int(part[:-1])
        else:
            return int(part)

    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid session format: '{s}'. Use MIN-MAX e.g. 90m-180m")
    return to_minutes(parts[0]), to_minutes(parts[1])


def _cmd_add_project(context: dict, args) -> None:
    """--add-project: create a long-running project budget in DB + Todoist."""
    import dateparser

    from src.db import create_project_budget, setup_database
    from src.todoist_client import TodoistClient

    setup_database()

    name = args.add_project
    budget_hours = args.budget
    session_str = args.session or "60m-180m"
    deadline_str = args.deadline
    priority_label = (args.priority or "P2").upper()

    try:
        session_min, session_max = _parse_session_range(session_str)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    deadline_iso = None
    if deadline_str:
        parsed = dateparser.parse(
            deadline_str,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed is None:
            print(f"[ERROR] Could not parse deadline: '{deadline_str}'")
            sys.exit(1)
        deadline_iso = parsed.date().isoformat()

    priority_int = _PRIORITY_API.get(priority_label, 3)

    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)

    task_content = f"[Budget] {name}"
    try:
        task_id = client.create_task(
            content=task_content,
            priority=priority_int,
            deadline=deadline_iso,
            labels=["budget-task"],
        )
    except Exception as exc:
        print(f"[ERROR] Could not create Todoist task: {exc}")
        sys.exit(1)

    create_project_budget(
        todoist_task_id=task_id,
        project_name=name,
        total_budget_hours=budget_hours,
        session_min_minutes=session_min,
        session_max_minutes=session_max,
        deadline=deadline_iso,
        priority=priority_int,
    )

    print(f"\n  Project:   {name}")
    print(f"  Budget:    {budget_hours}h total")
    print(f"  Session:   {session_min}–{session_max}min")
    if deadline_iso:
        print(f"  Deadline:  {deadline_iso}")
    print(f"  Priority:  {priority_label}")
    print(f"  Task ID:   {task_id}")
    print(f"\n  Project budget created.")


def _cmd_update_project(context: dict, args) -> None:
    """--update-project: patch budget hours, session range, or deadline."""
    import dateparser

    from src.db import (
        add_to_budget,
        get_all_active_budgets,
        setup_database,
        update_budget_fields,
    )

    setup_database()
    name = args.update_project

    budgets = get_all_active_budgets()
    # Exact match first, then partial
    match = next(
        (b for b in budgets if b["project_name"].lower() == name.lower()), None
    )
    if match is None:
        matches = [b for b in budgets if name.lower() in b["project_name"].lower()]
        if len(matches) == 1:
            match = matches[0]
        elif len(matches) > 1:
            print(f"[ERROR] Ambiguous project name '{name}'. Matches:")
            for m in matches:
                print(f"  • {m['project_name']}")
            sys.exit(1)
        else:
            print(f"[ERROR] No active project budget matching '{name}'")
            sys.exit(1)

    task_id = match["todoist_task_id"]
    changed = False

    if args.add_budget is not None:
        new_rem = add_to_budget(task_id, float(args.add_budget))
        print(f"  Budget +{args.add_budget}h → {new_rem:.1f}h remaining")
        changed = True

    field_kw: dict = {}
    if args.set_session:
        try:
            smin, smax = _parse_session_range(args.set_session)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            sys.exit(1)
        field_kw["session_min_minutes"] = smin
        field_kw["session_max_minutes"] = smax
        print(f"  Session → {smin}–{smax}min")
        changed = True

    if args.set_deadline:
        parsed = dateparser.parse(
            args.set_deadline,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed is None:
            print(f"[ERROR] Could not parse deadline: '{args.set_deadline}'")
            sys.exit(1)
        deadline_iso = parsed.date().isoformat()
        field_kw["deadline"] = deadline_iso
        print(f"  Deadline → {deadline_iso}")
        changed = True

    if field_kw:
        update_budget_fields(task_id, **field_kw)

    if changed:
        print(f"\n  Updated: {match['project_name']}")
    else:
        print(
            f"  Nothing to update. Use --add-budget, --set-session, or --set-deadline."
        )


def _cmd_projects(context: dict) -> None:
    """--projects: display all active project budgets as a table."""
    from src.db import compute_deadline_pressure, get_all_active_budgets, setup_database

    setup_database()
    budgets = get_all_active_budgets()

    if not budgets:
        print("No active project budgets. Use --add-project to create one.")
        return

    _W = 76
    print(f"\n{'═' * _W}")
    print(f"  ACTIVE PROJECT BUDGETS")
    print(f"{'═' * _W}")
    print(
        f"  {'NAME':<26} {'REMAIN':>7} {'TOTAL':>7} {'SESSION':>13} {'DEADLINE':<12} {'PRESSURE':<10}"
    )
    print(f"  {'─' * 72}")

    for b in budgets:
        pressure = compute_deadline_pressure(b.get("deadline"), b["remaining_hours"])
        session_str = f"{b['session_min_minutes']}–{b['session_max_minutes']}min"
        deadline = b.get("deadline") or "—"
        p_label = _PRIORITY_LABEL.get(b.get("priority", 3), "P?")
        print(
            f"  {b['project_name']:<26} "
            f"{b['remaining_hours']:>6.1f}h "
            f"{b['total_budget_hours']:>6.1f}h "
            f"{session_str:>13} "
            f"{deadline:<12} "
            f"{pressure:<10}"
        )

    print(f"{'═' * _W}\n")


# ── Shared helper ──────────────────────────────────────────────────────────────


def _find_project_match(name: str) -> dict:
    """
    Find a single project_budgets row by case-insensitive name match.
    Exact match preferred over partial. Exits with error on 0 or >1 matches.
    """
    from src.db import find_budget_by_name

    matches = find_budget_by_name(name)
    if not matches:
        print(f"[ERROR] No project budget matching '{name}' found.")
        sys.exit(1)
    # Prefer exact match
    exact = [m for m in matches if m["project_name"].lower() == name.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    print(f"[ERROR] Ambiguous project name '{name}'. Matches:")
    for m in matches:
        print(f"  • {m['project_name']}")
    sys.exit(1)


# ── --unplan ───────────────────────────────────────────────────────────────────


def _cmd_unplan(context: dict, target_date: "date", task_filter: str | None) -> None:
    """--unplan [DATE] [--task NAME]: undo a confirmed --plan-day run."""
    from zoneinfo import ZoneInfo

    from src.db import (
        delete_schedule_log_for_date,
        delete_task_history_row,
        get_task_history_for_date,
        setup_database,
    )
    from src.todoist_client import TodoistClient

    setup_database()

    _tz_aliases = {
        "PST": "America/Vancouver",
        "PST/Vancouver": "America/Vancouver",
        "Vancouver": "America/Vancouver",
    }
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz = ZoneInfo(_tz_aliases.get(tz_str, tz_str))

    date_str = target_date.isoformat()
    rows = get_task_history_for_date(date_str)

    if not rows:
        print(f"No confirmed plan found for {date_str}.")
        return

    # ── Apply --task filter if provided ───────────────────────────────────────
    single_task_mode = task_filter is not None
    if single_task_mode:
        needle = task_filter.lower()
        matched = [r for r in rows if needle in r["task_name"].lower()]
        if not matched:
            print(
                f"[ERROR] No task matching '{task_filter}' found in plan for {date_str}."
            )
            return
        if len(matched) > 1:
            print(f"Multiple tasks match '{task_filter}'. Pick one:")
            for i, r in enumerate(matched, 1):
                print(f"  [{i}] {r['task_name']}")
            try:
                pick = int(input("  > ").strip())
                rows = [matched[pick - 1]]
            except (ValueError, IndexError, EOFError):
                print("[ERROR] Invalid selection.")
                return
        else:
            rows = matched

    # ── Build display with scheduled time window ───────────────────────────────
    def _fmt_row(r: dict) -> str:
        scheduled = r.get("scheduled_at", "")
        dur = r.get("estimated_duration_mins") or 0
        try:
            start_dt = datetime.fromisoformat(scheduled).astimezone(tz)
            end_dt = start_dt + timedelta(minutes=dur)
            return f"{r['task_name']}  (was {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')})"
        except Exception:
            return r["task_name"]

    if single_task_mode:
        row = rows[0]
        print(f"\n  Unschedule \"{row['task_name']}\"?")
        print(f"  {_fmt_row(row)}")
    else:
        print(f"\n  ⚠️  This will unschedule {len(rows)} task(s) for {date_str}:")
        for r in rows:
            print(f"      • {_fmt_row(r)}")
        print(
            f"\n  This does not delete tasks. They will return to your unscheduled task list."
        )

    try:
        confirm = input("  Confirm? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("  Cancelled.")
        return

    # ── Execute ───────────────────────────────────────────────────────────────
    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)
    n_cleared = 0

    for r in rows:
        task_id = r["task_id"]
        try:
            client.clear_task_due(task_id)
        except Exception as exc:
            if "404" in str(exc):
                print(
                    f"  [INFO] '{r['task_name']}' not found in Todoist — cleaning DB only."
                )
            else:
                print(
                    f"  [WARN] Could not clear Todoist schedule for '{r['task_name']}': {exc}"
                )

        delete_task_history_row(task_id, date_str)
        n_cleared += 1

    if not single_task_mode:
        delete_schedule_log_for_date(date_str)

    if single_task_mode:
        print(f"\n  ✅ Unscheduled '{rows[0]['task_name']}'.")
        print(f"     Run --plan-day {date_str} to reschedule it.")
    else:
        print(f"\n  ✅ Unplanned {date_str}: {n_cleared} task(s) unscheduled.")
        print(f"     Run --plan-day {date_str} to reschedule.")


# ── --delete-project ───────────────────────────────────────────────────────────


def _cmd_delete_project(context: dict, args) -> None:
    """--delete-project NAME [--keep-task]: remove a project budget entry."""
    from src.db import (
        delete_project_budget,
        delete_task_history_all,
        setup_database,
    )
    from src.todoist_client import TodoistClient

    setup_database()
    budget = _find_project_match(args.delete_project)
    keep_task = getattr(args, "keep_task", False)

    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)

    # Fetch task content for display
    task_content = f"[Budget] {budget['project_name']}"
    try:
        t = client.get_task_by_id(budget["todoist_task_id"])
        if t:
            task_content = t.content
    except Exception:
        pass

    p_label = _PRIORITY_LABEL.get(budget.get("priority", 3), "P?")
    deadline = budget.get("deadline") or "none"
    session_str = f"{budget['session_min_minutes']}–{budget['session_max_minutes']}min"

    print(f"\n  Delete project budget: \"{budget['project_name']}\"")
    print(
        f"    Budget:   {budget['remaining_hours']:.1f}h of {budget['total_budget_hours']:.1f}h remaining"
    )
    print(
        f"    Sessions: {session_str}  |  Priority: {p_label}  |  Deadline: {deadline}"
    )
    print(f"    Todoist task: \"{task_content}\" (ID: {budget['todoist_task_id']})")
    if keep_task:
        print("    The Todoist task will be kept (unscheduled).")
    else:
        print("    The Todoist task will also be deleted.")

    try:
        confirm = input("\n  Confirm? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("  Cancelled.")
        return

    # ── Execute ───────────────────────────────────────────────────────────────
    delete_project_budget(budget["todoist_task_id"])
    delete_task_history_all(budget["todoist_task_id"])

    if keep_task:
        try:
            client.clear_task_due(budget["todoist_task_id"])
        except Exception as exc:
            print(f"  [WARN] Could not clear Todoist task schedule: {exc}")
        task_outcome = "Todoist task kept (unscheduled)."
    else:
        try:
            client.delete_task(budget["todoist_task_id"])
        except Exception as exc:
            print(f"  [WARN] Could not delete Todoist task: {exc}")
        task_outcome = "Todoist task deleted."

    print(f"\n  ✅ Project \"{budget['project_name']}\" deleted.")
    print(f"     {task_outcome}")


# ── --reset-project ────────────────────────────────────────────────────────────


def _cmd_reset_project(context: dict, args) -> None:
    """--reset-project NAME: reset remaining hours back to total budget."""
    from src.db import (
        delete_task_history_all,
        reset_project_budget_hours,
        setup_database,
    )
    from src.todoist_client import TodoistClient

    setup_database()
    budget = _find_project_match(args.reset_project)

    print(f"\n  Reset \"{budget['project_name']}\" remaining hours?")
    print(
        f"    Current:    {budget['remaining_hours']:.1f}h remaining of {budget['total_budget_hours']:.1f}h"
    )
    print(
        f"    After reset: {budget['total_budget_hours']:.1f}h remaining of {budget['total_budget_hours']:.1f}h"
    )
    print("  Also clears all task_history rows for this project.")

    try:
        confirm = input("\n  Confirm? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("  Cancelled.")
        return

    # ── Execute ───────────────────────────────────────────────────────────────
    new_hours = reset_project_budget_hours(budget["todoist_task_id"])
    delete_task_history_all(budget["todoist_task_id"])

    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)
    try:
        client.clear_task_due(budget["todoist_task_id"])
    except Exception as exc:
        print(f"  [WARN] Could not clear Todoist task schedule: {exc}")

    print(f"\n  ✅ Project \"{budget['project_name']}\" reset to {new_hours:.1f}h.")
    print("     Run --plan-day to schedule a fresh session.")


def _print_help() -> None:
    """Custom --help display."""
    print(
        """
╔══════════════════════════════════════════════════════════╗
║            AI Scheduling Agent — Command Reference       ║
╚══════════════════════════════════════════════════════════╝

DAILY WORKFLOW
──────────────
  python main.py --plan-day [DATE]
      Run the full AI scheduling pipeline.
      Fetches Todoist tasks + GCal events, enriches tasks,
      proposes a time-blocked schedule, and writes back to Todoist.

      DATE examples:  (default: today)
        --plan-day tomorrow
        --plan-day monday
        --plan-day "next friday"
        --plan-day 2026-04-10

  python main.py --review [DATE]
      Review the day's planned tasks interactively.
      Detects completed/rescheduled tasks, prompts for
      partial completion, and proposes reschedule slots.
      Also prompts for project budget hours worked.

      DATE examples:  (default: today)
        --review yesterday
        --review 2026-04-06

PROJECT BUDGETS (long-running work)
────────────────────────────────────
  python main.py --add-project "Project Name" \\
      --budget HOURS --session MIN-MAX --deadline DATE --priority P2

      --budget      Total hours budgeted (e.g. 22)
      --session     Session range in minutes (e.g. 90m-180m or 60-120)
      --deadline    Natural language or ISO date (e.g. "april 20")
      --priority    P1 / P2 / P3 / P4 (default: P2)

  python main.py --update-project "Project Name" \\
      [--add-budget HOURS] [--set-session MIN-MAX] [--set-deadline DATE]

  python main.py --projects
      Display all active project budgets with remaining hours,
      session ranges, deadlines, and deadline pressure status.

UTILITY COMMANDS
────────────────
  python main.py --unplan [DATE]           Clear a confirmed plan, ready to re-run
    python main.py --unplan                # today
    python main.py --unplan tomorrow
    python main.py --unplan --task "LinkedIn"   # single task only

  python main.py --delete-project "Name"  Remove a project budget entry
    python main.py --delete-project "PM Accelerator"
    python main.py --delete-project "PM Accelerator" --keep-task

  python main.py --reset-project "Name"   Reset remaining hours to full budget
    python main.py --reset-project "PM Accelerator"

VALIDATION
──────────
  python main.py --check
      Validate the full data pipeline (GCal + Todoist + scheduler)
      without calling the LLM. Safe to run any time.

TASK LABELING GUIDE
────────────────────
  @deep-work       Sustained focus. Scheduled in peak hours only (morning–early afternoon).
  @admin           Low-cognitive. Batched in afternoon.
  @waiting         Blocked on someone else. Never auto-scheduled.
  @quick           Under 15min. Batched into transition gaps.
  @in-progress     Partially done. Higher urgency than unstarted at same priority.

  Duration labels (required to schedule a task):
    @15min  @30min  @60min  @90min  @2h  @3h

PRIORITY
─────────
  P1 = Urgent/critical (API: 4)
  P2 = High            (API: 3)
  P3 = Medium          (API: 2)
  P4 = Default/unset   (API: 1)
"""
    )


def _resolve_target_date(date_arg: str) -> date:
    """
    Resolve the optional --plan-day date argument to a concrete date.
    Accepts: "" (today), "tomorrow", "monday", "next friday", "2026-04-07", etc.
    Uses dateparser to handle natural language. Exits with an error if unparseable.
    """
    if not date_arg:
        return date.today()

    import dateparser

    parsed = dateparser.parse(
        date_arg,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if parsed is None:
        print(f"[ERROR] Could not parse date: '{date_arg}'")
        print("  Examples: tomorrow, monday, next friday, 2026-04-07")
        sys.exit(1)

    return parsed.date()


def _cmd_plan_day(context: dict, target_date: date) -> None:
    """
    --plan-day [DATE]: filter → enrich → confirm priorities → schedule → display → write-back.
    Read-only except for optional priority writes in Step C and confirmed write-back in Step F.
    """
    from src.calendar_client import get_events
    from src.db import insert_schedule_log, insert_task_history, setup_database
    from src.llm import enrich_tasks, generate_schedule
    from src.scheduler import compute_free_windows, pack_schedule
    from src.todoist_client import TodoistClient, write_schedule_to_todoist

    # Load productivity_science.json (fail fast if missing)
    prod_science_path = Path(__file__).parent / "productivity_science.json"
    if not prod_science_path.exists():
        print("[ERROR] productivity_science.json not found in project root")
        sys.exit(1)
    with open(prod_science_path) as f:
        prod_science = json.load(f)

    setup_database()

    day_before = target_date - timedelta(days=1)
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")

    # ── GCal ──────────────────────────────────────────────────────────────────
    date_label = target_date.strftime("%A %b %d")
    print(f"[GCal] Fetching events for {date_label}…")
    events = []
    try:
        extra_cal_ids = context.get("calendar_ids", [])
        events = get_events(target_date, tz_str, extra_calendar_ids=extra_cal_ids)
        print(f"[GCal] {len(events)} event(s) found")
    except Exception as exc:
        print(f"[WARN] GCal fetch failed: {exc}")

    late_night_prior = False
    try:
        tz = ZoneInfo(tz_str)
        threshold_dt = _late_night_threshold_dt(day_before, context, tz)
        for ev in get_events(
            day_before, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        ):
            ev_end = ev.end if ev.end.tzinfo else ev.end.replace(tzinfo=tz)
            if not ev.is_all_day and ev_end >= threshold_dt:
                late_night_prior = True
                print(
                    f"[GCal] Late night on {day_before} ({ev.summary} @ {ev.end.strftime('%H:%M')}) — buffer extended"
                )
                break
    except Exception:
        pass

    # ── Todoist ───────────────────────────────────────────────────────────────
    print("[Todoist] Fetching tasks…")
    tasks = []
    todoist_client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))
    try:
        tasks = todoist_client.get_tasks("!date | today | overdue")
        print(f"[Todoist] {len(tasks)} task(s) found")
    except Exception as exc:
        print(f"[WARN] Todoist fetch failed: {exc}")

    # ── STEP A: Filter — already_scheduled / schedulable / skipped ───────────
    # Normalize timezone for comparison
    from zoneinfo import ZoneInfo

    _tz_aliases = {
        "PST": "America/Vancouver",
        "PST/Vancouver": "America/Vancouver",
        "Vancouver": "America/Vancouver",
    }
    _tz_str_norm = _tz_aliases.get(tz_str, tz_str)
    _tz = ZoneInfo(_tz_str_norm)

    already_scheduled = (
        []
    )  # has due_datetime on target_date — block time, show, skip LLM
    pinned_other_day = []  # has due_datetime on a different date — skip LLM, don't move
    schedulable = []  # has duration_minutes, no due_datetime — pass to LLM
    skipped = []  # no duration_minutes — skip entirely
    for _t in tasks:
        if _t.duration_minutes is None:
            skipped.append(_t)
            continue
        if _t.due_datetime is not None:
            _dt = _t.due_datetime
            if _dt.tzinfo is None:
                _dt = _dt.replace(tzinfo=_tz)
            else:
                _dt = _dt.astimezone(_tz)
            if _dt.date() == target_date:
                already_scheduled.append(_t)
            else:
                pinned_other_day.append(_t)
            continue
        schedulable.append(_t)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    print("[Scheduler] Computing free windows…")
    windows = compute_free_windows(
        events,
        target_date,
        context,
        late_night_prior=late_night_prior,
        scheduled_tasks=already_scheduled,
    )
    print(
        f"[Scheduler] {len(windows)} free window(s): "
        + ", ".join(
            f"{w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')}" for w in windows
        )
    )

    if not tasks:
        print("[INFO] No tasks to schedule. Exiting.")
        return
    if not windows:
        print(f"[INFO] No free windows on {date_label}. Exiting.")
        return

    if already_scheduled:
        print(
            f"\n📌  Already scheduled on {date_label}: {len(already_scheduled)} task(s)"
        )
        for t in already_scheduled:
            dt = (
                t.due_datetime.astimezone(_tz)
                if t.due_datetime.tzinfo
                else t.due_datetime.replace(tzinfo=_tz)
            )
            print(
                f"    • [{dt.strftime('%H:%M')}] {t.content} ({t.duration_minutes}min)"
            )

    if pinned_other_day:
        print(
            f"\n📎  Pinned to another day (not touched): {len(pinned_other_day)} task(s)"
        )
        for t in pinned_other_day:
            dt = (
                t.due_datetime.astimezone(_tz)
                if t.due_datetime.tzinfo
                else t.due_datetime.replace(tzinfo=_tz)
            )
            print(
                f"    • [{dt.strftime('%Y-%m-%d %H:%M')}] {t.content} ({t.duration_minutes}min)"
            )

    if skipped:
        print(f"\n⏭   Skipped (no duration label): {len(skipped)} task(s)")
        for t in skipped:
            print(f"    • {t.content}")
        print(
            "    → Add @15min / @30min / @60min / @90min / @2h / @3h label in Todoist to schedule these"
        )

    # ── Inject project budget synthetic tasks ─────────────────────────────────
    from src.db import compute_deadline_pressure, get_all_active_budgets, setup_database
    from src.models import TodoistTask as _TodoistTask

    budgets = get_all_active_budgets()
    budget_task_objects = []
    if budgets:
        # Budget tasks are always @deep-work — they can only be placed in
        # morning-peak or late-night windows. Using the full largest_window
        # (which may be an afternoon block) produces a session_dur that
        # exceeds the only window pack_schedule will actually place them in.
        # Filter to deep-work-eligible windows (morning + late night) so
        # session_dur never overshoots the available slot.
        dw_windows = [w for w in windows if w.block_type in ("morning", "late night")]
        largest_dw_window = max((w.duration_minutes for w in dw_windows), default=0)
        # Fall back to all windows if no DW-specific window exists today
        largest_window = largest_dw_window or max(
            (w.duration_minutes for w in windows), default=0
        )
        _pressure_weight = {
            "critical": 3,
            "at_risk": 2,
            "comfortable": 1,
            "no_deadline": 1,
        }
        _priority_weight = {4: 4, 3: 3, 2: 2, 1: 1}

        scored = []
        for b in budgets:
            pressure = compute_deadline_pressure(
                b.get("deadline"), b["remaining_hours"]
            )
            pw = _priority_weight.get(b.get("priority", 3), 2)
            dw = _pressure_weight.get(pressure, 1)
            score = pw * dw

            session_min = b["session_min_minutes"]
            session_max = b["session_max_minutes"]
            # Clamp to the largest DW-eligible window. Use whatever fits,
            # not the ideal minimum. Only skip if no DW windows exist at all.
            session_dur = (
                min(session_max, largest_window) if largest_window > 0 else session_min
            )

            scored.append((score, pressure, b, session_dur))

        scored.sort(key=lambda x: x[0], reverse=True)

        for score, pressure, b, session_dur in scored:
            t = _TodoistTask(
                id=b["todoist_task_id"],
                content=b["project_name"],
                project_id="",
                priority=b.get("priority", 3),
                due_datetime=None,
                deadline=b.get("deadline"),
                duration_minutes=session_dur,
                labels=["deep-work"],
                is_inbox=False,
                is_budget_task=True,
            )
            budget_task_objects.append(t)
            if pressure in ("critical", "at_risk"):
                print(
                    f"  ⚠️  Budget [{b['project_name']}]  {b['remaining_hours']:.1f}h remaining  "
                    f"[{pressure.upper()}]"
                )

        if budget_task_objects:
            print(
                f"\n[Budget] {len(budget_task_objects)} project budget session(s) added to schedule"
            )
            schedulable = budget_task_objects + schedulable

    if not schedulable:
        print("\n[INFO] No unscheduled tasks to plan. Exiting.")
        return

    print(f"\n[Scheduler] {len(schedulable)} schedulable task(s) continuing to LLM…")

    # task_map covers all tasks so pushed/flagged lookups still work for display
    task_map = {t.id: t for t in tasks}
    for t in budget_task_objects:
        task_map[t.id] = t

    # ── STEP B: Enrich schedulable tasks ──────────────────────────────────────
    print(f"[LLM] Step 1 — Enriching {len(schedulable)} tasks with {ENRICH_MODEL}…")
    enriched = enrich_tasks(schedulable, context, prod_science)
    print(f"[LLM] {len(enriched)} enrichment(s) returned")

    # ── STEP C: Priority confirmation for P4 / unset-priority tasks ───────────
    # Todoist API priority 1 = P4 = default/unset
    enriched_map = {e.get("task_id", ""): e for e in enriched}
    unset_items = [
        (i + 1, enriched_map[t.id], t)
        for i, t in enumerate(schedulable)
        if t.priority == 1 and "suggested_priority" in enriched_map.get(t.id, {})
    ]

    if unset_items:
        print(
            f"\n⚠️   {len(unset_items)} task(s) have no priority set. Review suggestions:\n"
        )
        for num, enr, t in unset_items:
            suggested = enr.get("suggested_priority", "P4")
            reason = enr.get("suggested_priority_reason", "")
            print(f'  [{num}] "{t.content}"  →  {suggested}')
            if reason:
                print(f'        └─ "{reason}"')

        raw_response = input(
            "\n  Accept all? [y] or override (e.g. 1=P3,2=P2) then press Enter: "
        ).strip()

        # Parse overrides: "1=P3,2=P2" → {1: "P3", 2: "P2"}
        overrides: dict[int, str] = {}
        if raw_response.lower() not in ("y", ""):
            for part in raw_response.split(","):
                part = part.strip()
                if "=" in part:
                    try:
                        idx_str, p_str = part.split("=", 1)
                        overrides[int(idx_str.strip())] = p_str.strip().upper()
                    except (ValueError, AttributeError):
                        pass

        # Write accepted priorities back to Todoist and update in-memory objects
        print()
        for num, enr, t in unset_items:
            final_label = overrides.get(num, enr.get("suggested_priority", "P4"))
            api_int = _PRIORITY_API.get(final_label, 1)
            try:
                todoist_client.update_task_priority(t.id, api_int)
                t.priority = (
                    api_int  # update in-memory so display shows correct priority
                )
                print(f'  ✓  "{t.content}"  →  {final_label}')
            except Exception as exc:
                print(f'  [WARN] Could not update priority for "{t.content}": {exc}')

    # ── STEP D: generate_schedule ──────────────────────────────────────────────
    # Build merged enrichment + task details for Step 2
    enriched_with_details = []
    for t in schedulable:
        base = enriched_map.get(
            t.id,
            {
                "task_id": t.id,
                "cognitive_load": "medium",
                "energy_requirement": "moderate",
                "suggested_block": "afternoon",
                "can_be_split": False,
                "scheduling_flags": ["never-schedule"] if "waiting" in t.labels else [],
            },
        )
        enriched_with_details.append(
            {
                **base,
                "content": t.content,
                "priority": _PRIORITY_LABEL.get(t.priority, "P4"),
                "duration_minutes": t.duration_minutes,
                "labels": t.labels,
                "deadline": t.deadline,
            }
        )

    print(f"\n[LLM] Step 2 — Generating schedule order with {SCHEDULE_MODEL}…")
    heuristics = prod_science.get("scheduling_heuristics_summary", {})
    schedule = generate_schedule(
        enriched_tasks=enriched_with_details,
        free_windows=windows,
        context=context,
        heuristics_summary=heuristics,
        target_date=target_date.isoformat(),
    )
    ordered_tasks = schedule.get("ordered_tasks", [])
    llm_pushed = schedule.get("pushed", [])
    flagged = schedule.get("flagged", [])
    reasoning_summary = schedule.get("reasoning_summary", "")
    print(
        f"[LLM] {len(ordered_tasks)} task(s) ordered, {len(llm_pushed)} pushed by LLM"
    )

    # ── STEP E: pack_schedule — Python handles all clock math ─────────────────
    print("[Scheduler] Packing schedule into free windows…")
    blocks, auto_pushed = pack_schedule(
        ordered_tasks=ordered_tasks,
        free_windows=windows,
        context=context,
        target_date=target_date,
    )
    # Merge LLM-pushed with auto-pushed (dedup by task_id)
    seen_ids = {p.get("task_id") for p in llm_pushed}
    for ap in auto_pushed:
        if ap.get("task_id") not in seen_ids:
            llm_pushed.append(ap)
            seen_ids.add(ap.get("task_id"))

    print(f"[Scheduler] {len(blocks)} block(s) placed, {len(llm_pushed)} total pushed")

    _display_schedule(
        blocks,
        llm_pushed,
        flagged,
        reasoning_summary,
        task_map,
        target_date,
        already_scheduled,
    )

    # ── STEP F: Confirm and write back ────────────────────────────────────────
    try:
        answer = input("Confirm schedule? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer != "y":
        print("Schedule discarded.")
        return

    # ── Write to Todoist ──────────────────────────────────────────────────────
    print("[Todoist] Writing schedule…")
    try:
        n_updated = write_schedule_to_todoist(
            scheduled_blocks=blocks,
            pushed_tasks=llm_pushed,
            task_map=task_map,
            context=context,
            api_token=os.getenv("TODOIST_API_TOKEN"),
        )
        print(f"✅ {n_updated} task(s) updated in Todoist.")
        print("📅 Check your Todoist calendar view to confirm blocks.")
    except Exception as exc:
        print(f"[ERROR] Todoist write-back failed: {exc}")
        return

    # ── Save to schedule_log ──────────────────────────────────────────────────
    now_iso = datetime.now().isoformat()
    proposed = {
        "reasoning_summary": reasoning_summary,
        "ordered_tasks": ordered_tasks,
        "blocks": [
            {
                "task_id": b.task_id,
                "task_name": b.task_name,
                "start_time": b.start_time.isoformat(),
                "end_time": b.end_time.isoformat(),
                "duration_minutes": b.duration_minutes,
            }
            for b in blocks
        ],
        "pushed": llm_pushed,
        "flagged": flagged,
    }
    insert_schedule_log(
        schedule_date=target_date.isoformat(),
        proposed_json=proposed,
        confirmed=True,
        confirmed_at=now_iso,
    )

    # ── Save per-task rows to task_history ────────────────────────────────────
    enriched_by_id = {e.get("task_id", ""): e for e in enriched}
    for block in blocks:
        if block.split_part == 2:
            continue  # don't double-log split tasks
        original = task_map.get(block.task_id)
        enr = enriched_by_id.get(block.task_id, {})
        insert_task_history(
            task_id=block.task_id,
            task_name=block.task_name,
            project_id=original.project_id if original else "",
            estimated_duration_mins=block.duration_minutes,
            scheduled_at=block.start_time.isoformat(),
            day_of_week=target_date.strftime("%A"),
            was_rescheduled=False,
            reschedule_count=0,
            was_late_night_prior=late_night_prior,
            cognitive_load_label=enr.get("cognitive_load"),
        )


def _cmd_review(context: dict, target_date: "date") -> None:
    """
    --review [DATE]: hybrid source of truth.

    task_history tells us WHICH tasks to review (only tasks scheduled via --plan-day).
    Todoist (get_task_by_id) tells us the STATUS of each task.

    Step 1: Load unreviewed task_history rows for target_date.
    Step 2: Check each task's status via Todoist — completed / externally rescheduled / incomplete.
    Step 3: Interactive [1-5] prompt for incomplete tasks.
    Step 4: Reschedule proposals using task_history (not Todoist) for double-booking prevention.
    """
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from src.calendar_client import get_events
    from src.db import (
        get_todays_task_history,
        insert_task_history,
        mark_task_partial,
        mark_task_rescheduled_externally,
        setup_database,
        upsert_task_completed,
    )
    from src.models import TodoistTask
    from src.scheduler import compute_free_windows
    from src.todoist_client import TodoistClient

    setup_database()

    _tz_aliases = {
        "PST": "America/Vancouver",
        "PST/Vancouver": "America/Vancouver",
        "Vancouver": "America/Vancouver",
    }
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _tz_aliases.get(tz_str, tz_str)
    tz = ZoneInfo(tz_str_norm)
    extra_cal_ids = context.get("calendar_ids", [])

    today = date.today()
    target_str = target_date.isoformat()
    now_iso = datetime.now(tz).isoformat()

    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)

    # ── Step 1: Load from task_history ────────────────────────────────────────
    print(f"\n[Review] Loading tasks for {target_str} from task_history...")
    rows = get_todays_task_history(target_str)
    if not rows:
        print(f"  No tasks were scheduled via --plan-day for {target_str}.")
        print(f"  Run: python main.py --plan-day {target_str}")
        return

    print(f"  {len(rows)} planned task(s) found\n")

    # ── Step 2: Check each task status via Todoist ────────────────────────────
    # A) task is None → completed (Todoist removes completed tasks from active list)
    # B) task found + due_datetime not on target_date → externally rescheduled
    # C) task found + due_datetime on target_date → still incomplete
    n_auto_completed = 0
    n_external = 0
    incomplete: list[tuple[dict, TodoistTask]] = []  # (row, task)

    for row in rows:
        task = client.get_task_by_id(row["task_id"])

        if task is None:
            # A) Completed
            upsert_task_completed(
                task_id=row["task_id"],
                task_name=row["task_name"],
                project_id=row.get("project_id", ""),
                estimated_duration_mins=row.get("estimated_duration_mins") or 30,
                actual_duration_mins=row.get("estimated_duration_mins") or 30,
                completed_at=now_iso,
                scheduled_at=row.get("scheduled_at"),
                day_of_week=row.get("day_of_week"),
            )
            print(f"  \u2705 {row['task_name']} (completed)")
            n_auto_completed += 1

        elif (
            task.due_datetime and task.due_datetime.astimezone(tz).date() != target_date
        ):
            # B) Externally rescheduled
            new_date = task.due_datetime.astimezone(tz).date()
            print(
                f"  \U0001f4c5 {row['task_name']} (rescheduled externally to {new_date}) \u2014 skipping"
            )
            mark_task_rescheduled_externally(row["task_id"])
            n_external += 1

        else:
            # C) Still incomplete and on target_date
            incomplete.append((row, task))

    if not incomplete:
        _W = 47
        print(f"\n{'=' * _W}")
        print(f"  REVIEW COMPLETE \u2014 {target_str}")
        print(f"{'=' * _W}")
        print(f"  Completed:    {n_auto_completed} task(s)")
        if n_external:
            print(
                f"  Ext. moved:   {n_external} task(s) (rescheduled in Todoist directly)"
            )
        print(f"  Rescheduled:  0 task(s)")
        print(f"{'=' * _W}\n")
        return

    # ── Step 3: Interactive prompt for incomplete tasks ───────────────────────
    def _r5(n: int) -> int:
        return max(5, round(n / 5) * 5)

    def _r15(n: int) -> int:
        return max(15, round(n / 15) * 15)

    # (row, task, remaining_minutes, status: "not_started" | "partial" | "done")
    incomplete_with_remaining: list[tuple[dict, TodoistTask, int, str]] = []

    for row, task in incomplete:
        est = row.get("estimated_duration_mins") or 30
        reschedule_count = row.get("reschedule_count") or 0
        p_str = _PRIORITY_LABEL.get(task.priority, "P?")

        bands = [(0.25, "~25%"), (0.50, "~50%"), (0.75, "~75%")]

        reschedule_ctx = (
            f"  (rescheduled {reschedule_count} times)" if reschedule_count > 1 else ""
        )
        print(
            f'  \u274c "{row["task_name"]}"  (estimated: {est}min, {p_str}{reschedule_ctx})'
        )
        print("     How far did you get?")
        print("     [1] Didn't start")
        for i, (pct, label) in enumerate(bands, 2):
            done = _r5(int(est * pct))
            left = _r5(max(5, est - done))
            print(f"     [{i}] {label} done  (~{done}min done, ~{left}min remaining)")
        print("     [5] Actually done \u2713")

        try:
            choice = input("     > ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"

        if choice == "5":
            print("     \u2705 Marked complete.\n")
            upsert_task_completed(
                task_id=row["task_id"],
                task_name=row["task_name"],
                project_id=row.get("project_id", ""),
                estimated_duration_mins=est,
                actual_duration_mins=est,
                completed_at=now_iso,
                scheduled_at=row.get("scheduled_at"),
                day_of_week=row.get("day_of_week"),
            )
            incomplete_with_remaining.append((row, task, 0, "done"))

        elif choice == "1":
            print()
            incomplete_with_remaining.append((row, task, est, "not_started"))

        elif choice in ("2", "3", "4"):
            pct = bands[int(choice) - 2][0]
            done = _r15(int(est * pct))
            remaining = max(15, est - done)
            try:
                client.add_in_progress_label(row["task_id"])
            except Exception as exc:
                print(f"     [WARN] Could not add @in-progress label: {exc}")
            mark_task_partial(row["task_id"], target_str, done)
            print()
            incomplete_with_remaining.append((row, task, remaining, "partial"))

        else:
            print()
            incomplete_with_remaining.append((row, task, est, "not_started"))

    # ── Step 4: Reschedule incomplete tasks ───────────────────────────────────
    to_reschedule = [
        (row, task, rem, st)
        for row, task, rem, st in incomplete_with_remaining
        if st != "done"
    ]

    # (row, remaining, candidate_date|None, slot_start|None, slot_end|None)
    proposals: list[
        tuple[dict, int, "date | None", "datetime | None", "datetime | None"]
    ] = []
    # Tracks tasks placed this session to avoid inter-task collisions
    session_tasks_by_day: dict["date", list[TodoistTask]] = {}

    if to_reschedule:
        print(f"  {chr(9472) * 51}")
        print("  RESCHEDULING INCOMPLETE TASKS")
        print(f"  {chr(9472) * 51}")

        for row, task, remaining, _status in to_reschedule:
            placed = False
            for days_ahead in range(1, 8):
                candidate = today + timedelta(days=days_ahead)
                candidate_str_inner = candidate.isoformat()

                try:
                    events = get_events(
                        candidate, tz_str, extra_calendar_ids=extra_cal_ids
                    )
                except Exception:
                    events = []

                # Use task_history as the source of already-blocked time.
                # This prevents proposing slots that --plan-day has already filled.
                db_rows = get_todays_task_history(candidate_str_inner)
                db_blocked: list[TodoistTask] = []
                for db_row in db_rows:
                    if db_row.get("scheduled_at"):
                        try:
                            sched_dt = datetime.fromisoformat(
                                db_row["scheduled_at"]
                            ).astimezone(tz)
                            db_blocked.append(
                                TodoistTask(
                                    id=db_row["task_id"],
                                    content=db_row["task_name"],
                                    project_id=db_row.get("project_id", ""),
                                    priority=1,
                                    due_datetime=sched_dt,
                                    deadline=None,
                                    duration_minutes=db_row.get(
                                        "estimated_duration_mins"
                                    )
                                    or 30,
                                    labels=[],
                                    is_inbox=False,
                                )
                            )
                        except Exception:
                            pass

                session_tasks = session_tasks_by_day.get(candidate, [])
                windows = compute_free_windows(
                    events,
                    candidate,
                    context,
                    scheduled_tasks=db_blocked + session_tasks,
                )

                for window in windows:
                    if window.duration_minutes >= remaining:
                        slot_start = window.start
                        slot_end = slot_start + timedelta(minutes=remaining)
                        proposals.append(
                            (row, remaining, candidate, slot_start, slot_end)
                        )

                        # Reserve this slot for subsequent tasks in this session
                        placeholder = TodoistTask(
                            id=row["task_id"] + "_placeholder",
                            content=row["task_name"],
                            project_id=row.get("project_id", ""),
                            priority=1,
                            due_datetime=slot_start,
                            deadline=None,
                            duration_minutes=remaining,
                            labels=[],
                            is_inbox=False,
                        )
                        session_tasks_by_day.setdefault(candidate, []).append(
                            placeholder
                        )
                        placed = True
                        break

                if placed:
                    break

            if not placed:
                proposals.append((row, remaining, None, None, None))

        for row, remaining, cand_date, slot_start, slot_end in proposals:
            if cand_date is None:
                print(
                    f"\n  \u26a0\ufe0f  {row['task_name']} \u2192 needs manual scheduling"
                )
            else:
                day_label = (
                    "Tomorrow"
                    if cand_date == today + timedelta(days=1)
                    else cand_date.strftime("%A %b %d")
                )
                print(
                    f"\n  \u2192  {row['task_name']}"
                    f" \u2192 {day_label} {slot_start.strftime('%H:%M')}\u2013{slot_end.strftime('%H:%M')}"
                    f"  ({remaining}min)"
                )

        try:
            confirm = input("\n  Confirm reschedule? [y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "n"

        n_rescheduled = 0
        n_needs_attention = 0

        if confirm == "y":
            for row, remaining, cand_date, slot_start, slot_end in proposals:
                if cand_date is None:
                    n_needs_attention += 1
                    continue
                try:
                    client.clear_task_schedule(row["task_id"])
                    client.schedule_task(row["task_id"], slot_start, remaining)

                    orig_at = row.get("scheduled_at", "")
                    try:
                        orig_str = (
                            datetime.fromisoformat(orig_at).strftime("%Y-%m-%d %H:%M")
                            if orig_at
                            else "unknown"
                        )
                    except Exception:
                        orig_str = orig_at or "unknown"
                    comment = (
                        f"Rescheduled from {orig_str}. "
                        f"Reason: incomplete \u2014 rescheduled via --review."
                    )
                    client.add_comment(row["task_id"], comment)

                    insert_task_history(
                        task_id=row["task_id"],
                        task_name=row["task_name"],
                        project_id=row.get("project_id", ""),
                        estimated_duration_mins=remaining,
                        scheduled_at=slot_start.isoformat(),
                        day_of_week=cand_date.strftime("%A"),
                        was_rescheduled=True,
                        cognitive_load_label=row.get("cognitive_load_label"),
                    )
                    n_rescheduled += 1
                except Exception as exc:
                    print(f"  [WARN] Could not reschedule '{row['task_name']}': {exc}")
        else:
            n_rescheduled = 0
            n_needs_attention = sum(1 for _, _, d, _, _ in proposals if d is None)
    else:
        n_rescheduled = 0
        n_needs_attention = 0

    # ── Budget session review ─────────────────────────────────────────────────
    from src.db import decrement_budget, get_all_active_budgets

    active_budgets = get_all_active_budgets()
    if active_budgets:
        print(f"\n  {chr(9472) * 51}")
        print("  PROJECT BUDGET SESSIONS")
        print(f"  {chr(9472) * 51}")
        for b in active_budgets:
            deadline_part = (
                f"  (deadline: {b['deadline']})" if b.get("deadline") else ""
            )
            print(
                f"\n  [{b['project_name']}]  "
                f"{b['remaining_hours']:.1f}h remaining{deadline_part}"
            )
            print(
                "  Hours worked today? [0] None  [1] 1h  [2] 2h  [3] 3h  "
                "[4] 4h  [5] 5h  [6] 6h  [7] 7h"
            )
            try:
                choice = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "0"
            try:
                hours_worked = max(0, min(7, int(choice)))
            except ValueError:
                hours_worked = 0
            if hours_worked > 0:
                new_remaining = decrement_budget(
                    b["todoist_task_id"], float(hours_worked)
                )
                print(
                    f"  → {b['remaining_hours']:.1f}h \u2212 {hours_worked}h = {new_remaining:.1f}h remaining"
                )
                if new_remaining == 0:
                    try:
                        client.close_task(b["todoist_task_id"])
                        print("  \u2705 Budget exhausted — Todoist task closed")
                    except Exception as exc:
                        print(f"  [WARN] Could not close Todoist task: {exc}")
            else:
                print("  (no change)")

    # ── Summary ───────────────────────────────────────────────────────────────
    _W = 47
    n_completed_total = n_auto_completed + sum(
        1 for _, _, _, st in incomplete_with_remaining if st == "done"
    )
    print(f"\n{'=' * _W}")
    print(f"  REVIEW COMPLETE \u2014 {target_str}")
    print(f"{'=' * _W}")
    print(f"  Completed:    {n_completed_total} task(s)")
    if n_external:
        print(f"  Ext. moved:   {n_external} task(s) (rescheduled in Todoist directly)")
    print(f"  Rescheduled:  {n_rescheduled} task(s)")
    if n_needs_attention:
        print(
            f"  Needs attention: {n_needs_attention} task(s) \u2014 schedule manually"
        )
    print(f"{'=' * _W}\n")


def main() -> None:
    # Show custom help when invoked with no arguments
    if len(sys.argv) == 1:
        _print_help()
        return

    parser = argparse.ArgumentParser(
        description="AI Scheduling Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plan-day", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--review", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--add-task", type=str, metavar="TASK")

    # Project budget commands
    parser.add_argument("--add-project", type=str, metavar="NAME")
    parser.add_argument("--budget", type=float, metavar="HOURS")
    parser.add_argument("--session", type=str, metavar="MIN-MAX")
    parser.add_argument("--deadline", type=str, metavar="DATE")
    parser.add_argument("--priority", type=str, metavar="P1|P2|P3|P4")

    parser.add_argument("--update-project", type=str, metavar="NAME")
    parser.add_argument("--add-budget", type=float, metavar="HOURS")
    parser.add_argument("--set-session", type=str, metavar="MIN-MAX")
    parser.add_argument("--set-deadline", type=str, metavar="DATE")

    parser.add_argument("--projects", action="store_true")

    # Utility commands
    parser.add_argument("--unplan", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument(
        "--task",
        type=str,
        metavar="TASK_NAME",
        help="Filter --unplan to a single task by name",
    )
    parser.add_argument("--delete-project", type=str, metavar="NAME")
    parser.add_argument(
        "--keep-task",
        action="store_true",
        help="With --delete-project: keep the Todoist task",
    )
    parser.add_argument("--reset-project", type=str, metavar="NAME")

    args = parser.parse_args()

    if args.help:
        _print_help()
        return

    context = _load_config()

    if args.check:
        _cmd_check(context)
    elif args.plan_day is not None:
        target_date = _resolve_target_date(args.plan_day)
        _cmd_plan_day(context, target_date)
    elif args.review is not None:
        target_date = _resolve_target_date(args.review)
        _cmd_review(context, target_date)
    elif args.add_project:
        if args.budget is None:
            print("[ERROR] --add-project requires --budget HOURS")
            sys.exit(1)
        _cmd_add_project(context, args)
    elif args.update_project:
        _cmd_update_project(context, args)
    elif args.projects:
        _cmd_projects(context)
    elif args.unplan is not None:
        target_date = _resolve_target_date(args.unplan)
        _cmd_unplan(context, target_date, args.task)
    elif args.delete_project:
        _cmd_delete_project(context, args)
    elif args.reset_project:
        _cmd_reset_project(context, args)
    elif args.add_task:
        print("[ERROR] --add-task not yet implemented")
        sys.exit(1)
    else:
        _print_help()


if __name__ == "__main__":
    main()
