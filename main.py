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


def _has_pre_meeting(block, events: list, context: dict) -> bool:
    """Return True if a Flamingo GCal event starts within 45 min after block.end_time."""
    flamingo_color = (
        context.get("calendar_rules", {})
        .get("flamingo", {})
        .get("color_id", "4")
    )
    for ev in events:
        if ev.is_all_day or ev.color_id != flamingo_color:
            continue
        gap_mins = int((ev.start - block.end_time).total_seconds() / 60)
        if 0 <= gap_mins <= 45:
            return True
    return False


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
        # Budget tasks are stored in task_history as "Project Name" (without the
        # "[Budget] " prefix that appears in Todoist). Strip it so that searching
        # for "[Budget] PM Accelerator JAA 1" matches "PM Accelerator JAA 1".
        if needle.startswith("[budget] "):
            needle = needle[len("[budget] "):]
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


def _handle_no_room(
    client,
    new_task,
    target_date: "date",
    context: dict,
    tz,
    events: list,
    tz_str: str,
) -> None:
    """Offer options when the urgent task doesn't fit anywhere today."""
    from src.calendar_client import get_events as _get_events
    from src.scheduler import compute_free_windows

    tomorrow = target_date + timedelta(days=1)

    print("  Options:")
    print("  [1] Schedule it first thing tomorrow instead")
    print("  [2] Cancel (I'll handle it manually)")
    try:
        choice = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        choice = "2"

    if choice != "1":
        print("Cancelled — no changes made.")
        return

    tomorrow_events = []
    try:
        tomorrow_events = _get_events(
            tomorrow, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        )
    except Exception:
        pass

    tom_windows = compute_free_windows(tomorrow_events, tomorrow, context)
    if not tom_windows:
        print(f"No free windows found for {tomorrow}. Please schedule manually.")
        return

    slot = None
    for w in tom_windows:
        if w.duration_minutes >= new_task.duration_minutes:
            slot = w.start
            break
    if slot is None:
        slot = tom_windows[0].start

    try:
        client.schedule_task(new_task.id, slot, new_task.duration_minutes)
        print(
            f"✅ '{new_task.content}' scheduled for {tomorrow.strftime('%a %b %d')} "
            f"at {slot.strftime('%H:%M')}."
        )
    except Exception as exc:
        print(f"[ERROR] Could not schedule: {exc}")


def _cmd_add_task(context: dict, search_text: str, target_date: "date") -> None:
    """--add-task SEARCH_TEXT [--date DATE]: insert urgent task, replan rest of day."""
    from src.calendar_client import get_events
    from src.db import (
        compute_deadline_pressure,
        delete_task_history_row,
        get_all_active_budgets,
        get_budget_by_task_id,
        get_task_history_for_replan,
        insert_schedule_log,
        insert_task_history,
    )
    from src.llm import enrich_tasks, generate_schedule
    from src.models import TodoistTask as _TodoistTask
    from src.scheduler import compute_free_windows, pack_schedule
    from src.todoist_client import TodoistClient
    from zoneinfo import ZoneInfo

    _PL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
    _tz_aliases = {
        "PST": "America/Vancouver",
        "PST/Vancouver": "America/Vancouver",
        "Vancouver": "America/Vancouver",
    }
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _tz_aliases.get(tz_str, tz_str)
    tz = ZoneInfo(tz_str_norm)
    today_str = target_date.isoformat()

    client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))

    # ── STEP 1: Find the task ─────────────────────────────────────────────────
    print(f"[Todoist] Searching all tasks for '{search_text}'…")
    all_tasks = client.get_all_tasks()
    query = search_text.lower()

    candidates = []
    for t in all_tasks:
        if query not in t.content.lower():
            continue
        # Warn and skip if already scheduled today
        if t.due_datetime is not None:
            dt = t.due_datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            else:
                dt = dt.astimezone(tz)
            if dt.date() == target_date:
                print(
                    f"Task already scheduled today: '{t.content}'\n"
                    f"Use --unplan --task to remove it first, then re-add."
                )
                return
        candidates.append(t)

    if not candidates:
        print(
            f"No task found matching '{search_text}'.\n"
            f"Check the task exists in Todoist and has no scheduled time yet."
        )
        return

    if len(candidates) == 1:
        new_task = candidates[0]
        dur_str = f"{new_task.duration_minutes}min" if new_task.duration_minutes else "no duration"
        print(f"Found: '{new_task.content}' ({_PL.get(new_task.priority, 'P4')}, {dur_str})")
    else:
        print(f"Multiple tasks match '{search_text}':")
        for i, t in enumerate(candidates, 1):
            dur_str = f"{t.duration_minutes}min" if t.duration_minutes else "no duration"
            print(f"  [{i}] {t.content} ({_PL.get(t.priority, 'P4')}, {dur_str})")
        try:
            raw = input("Pick one (or 0 to cancel): ").strip()
            choice = int(raw)
        except (ValueError, EOFError):
            print("Cancelled.")
            return
        if choice == 0:
            print("Cancelled.")
            return
        if not 1 <= choice <= len(candidates):
            print("Invalid selection.")
            return
        new_task = candidates[choice - 1]

    # ── STEP 2: Validate ──────────────────────────────────────────────────────
    if new_task.duration_minutes is None:
        print(
            "Task found but has no duration label.\n"
            "Add @15min / @30min / @60min etc. in Todoist first."
        )
        return

    # ── STEP 3: Build replan window ───────────────────────────────────────────
    now_dt = datetime.now(tz=tz)
    extra_mins = (5 - now_dt.minute % 5) % 5
    if extra_mins == 0 and (now_dt.second > 0 or now_dt.microsecond > 0):
        extra_mins = 5
    replan_from = (now_dt + timedelta(minutes=extra_mins)).replace(
        second=0, microsecond=0
    )

    already_done, to_replan = get_task_history_for_replan(today_str, replan_from.isoformat())

    if not already_done and not to_replan:
        print("No confirmed plan for today — scheduling in next available window only.")

    print(f"\nReplanning from {replan_from.strftime('%H:%M')} onwards.")
    print(f"Already done or in progress ({len(already_done)} task(s)): kept as-is")
    print(f"To replan ({len(to_replan)} task(s)): will be rescheduled")

    # ── STEP 4: Recompute free windows ────────────────────────────────────────
    print("\n[GCal] Fetching events…")
    events = []
    try:
        events = get_events(
            target_date, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        )
        print(f"[GCal] {len(events)} event(s)")
    except Exception as exc:
        print(f"[WARN] GCal fetch failed: {exc}")

    # Convert already_done rows to blocked tasks (treat as in-flight even if not confirmed done)
    blocked_tasks: list[_TodoistTask] = []
    for row in already_done:
        if row.get("scheduled_at") and row.get("estimated_duration_mins"):
            try:
                dt = datetime.fromisoformat(row["scheduled_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
            except ValueError:
                continue
            blocked_tasks.append(
                _TodoistTask(
                    id=row["task_id"],
                    content=row.get("task_name", ""),
                    project_id="",
                    priority=1,
                    due_datetime=dt,
                    deadline=None,
                    duration_minutes=row["estimated_duration_mins"],
                    labels=[],
                    is_inbox=False,
                )
            )

    windows = compute_free_windows(
        events,
        target_date,
        context,
        scheduled_tasks=blocked_tasks,
        start_override=replan_from,
    )
    total_free = sum(w.duration_minutes for w in windows)
    print(
        f"[Scheduler] {len(windows)} free window(s): "
        + (
            ", ".join(
                f"{w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')}"
                for w in windows
            )
            or "none"
        )
    )

    # ── STEP 5: Build task list ───────────────────────────────────────────────
    # Fetch to_replan tasks from Todoist for current state
    replan_tasks: list[_TodoistTask] = []
    for row in to_replan:
        t = client.get_task_by_id(row["task_id"])
        if t is not None:
            replan_tasks.append(t)

    # Re-inject budget sessions that were in to_replan
    budgets_list = get_all_active_budgets()
    budget_ids = {b["todoist_task_id"] for b in budgets_list}
    budgets_map = {b["todoist_task_id"]: b for b in budgets_list}
    budget_in_replan = [t for t in replan_tasks if t.id in budget_ids]
    replan_tasks = [t for t in replan_tasks if t.id not in budget_ids]

    if windows and budget_in_replan:
        dw_windows = [w for w in windows if w.block_type in ("morning", "late night")]
        largest_dw = max((w.duration_minutes for w in dw_windows), default=0)
        largest_any = max((w.duration_minutes for w in windows), default=0)
        largest_w = largest_dw or largest_any
        for bt in budget_in_replan:
            b = budgets_map.get(bt.id)
            if not b:
                continue
            smin, smax = b["session_min_minutes"], b["session_max_minutes"]
            session_dur = min(smax, largest_w) if largest_w > 0 else smin
            replan_tasks.append(
                _TodoistTask(
                    id=bt.id,
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
            )

    # Urgent task goes first
    all_schedulable = [new_task] + replan_tasks

    # ── STEP 6: LLM chain ─────────────────────────────────────────────────────
    if not windows:
        print(
            f"\n⚠️  Not enough time today for '{new_task.content}' ({new_task.duration_minutes}min)."
        )
        print(f"   Remaining free time: 0min across 0 windows.")
        _handle_no_room(client, new_task, target_date, context, tz, events, tz_str)
        return

    prod_science_path = Path(__file__).parent / "productivity_science.json"
    prod_science = {}
    if prod_science_path.exists():
        with open(prod_science_path) as f:
            prod_science = json.load(f)

    print(f"\n[LLM] Step 1 — Enriching {len(all_schedulable)} task(s)…")
    enriched = enrich_tasks(all_schedulable, context, prod_science)

    # Force urgent-insert flag on the new task's enrichment
    for e in enriched:
        if e.get("task_id") == new_task.id:
            flags = e.get("scheduling_flags", [])
            if "urgent-insert" not in flags:
                flags.insert(0, "urgent-insert")
            e["scheduling_flags"] = flags
            e["suggested_block"] = "First available slot — emergency insertion"
            break

    enriched_map = {e["task_id"]: e for e in enriched}
    enriched_with_details = []
    for t in all_schedulable:
        base = enriched_map.get(
            t.id,
            {
                "task_id": t.id,
                "cognitive_load": "medium",
                "energy_requirement": "moderate",
                "suggested_block": "afternoon",
                "can_be_split": False,
                "scheduling_flags": [],
            },
        )
        enriched_with_details.append(
            {
                **base,
                "content": t.content,
                "priority": _PL.get(t.priority, "P4"),
                "duration_minutes": t.duration_minutes,
                "labels": t.labels,
                "deadline": t.deadline,
            }
        )

    # Inject urgent-insert hard rule into context for Step 2
    replan_context = dict(context)
    replan_context["rules"] = {
        "hard": list(context.get("rules", {}).get("hard", []))
        + [
            f"The first task in this list is an emergency insertion (flag: urgent-insert). "
            f"It MUST be the first task in ordered_tasks and scheduled in the first available "
            f"slot from {replan_from.strftime('%H:%M')}. No exceptions."
        ],
        "soft": list(context.get("rules", {}).get("soft", [])),
    }

    print("[LLM] Step 2 — Generating replan schedule order…")
    heuristics = prod_science.get("scheduling_heuristics_summary", {})
    schedule_result = generate_schedule(
        enriched_tasks=enriched_with_details,
        free_windows=windows,
        context=replan_context,
        heuristics_summary=heuristics,
        target_date=target_date.isoformat(),
    )
    ordered_tasks = schedule_result.get("ordered_tasks", [])
    llm_pushed = schedule_result.get("pushed", [])
    print(f"[LLM] {len(ordered_tasks)} task(s) ordered, {len(llm_pushed)} pushed by LLM")

    # Enforce urgent task first regardless of LLM ordering
    urgent_first = [t for t in ordered_tasks if t.get("task_id") == new_task.id]
    rest_ordered = [t for t in ordered_tasks if t.get("task_id") != new_task.id]
    ordered_tasks = urgent_first + rest_ordered

    # Carry over LLM-pushed never-schedule tasks
    ordered_ids = {t.get("task_id") for t in ordered_tasks}
    for p in llm_pushed:
        if p.get("task_id") not in ordered_ids:
            ordered_tasks.append(
                {
                    "task_id": p.get("task_id", ""),
                    "task_name": p.get("task_name", ""),
                    "duration_minutes": 30,
                    "break_after_minutes": 0,
                    "can_be_split": False,
                    "block_label": "",
                    "placement_reason": p.get("reason", ""),
                    "scheduling_flags": ["never-schedule"],
                }
            )

    print("[Scheduler] Packing replan schedule…")
    blocks, auto_pushed = pack_schedule(
        ordered_tasks=ordered_tasks,
        free_windows=windows,
        context=context,
        target_date=target_date,
    )
    print(f"[Scheduler] {len(blocks)} block(s) placed, {len(auto_pushed)} pushed")

    # ── STEP 7: Display with diff ─────────────────────────────────────────────
    task_map = {t.id: t for t in all_schedulable}
    original_by_id = {row["task_id"]: row for row in to_replan}
    new_by_id = {b.task_id: b for b in blocks}
    pushed_ids = {p["task_id"] for p in auto_pushed}

    print()
    print("═" * 57)
    print(f"  UPDATED SCHEDULE — from {replan_from.strftime('%H:%M')} onwards")
    print("═" * 57)

    if blocks:
        print()
        print("  ─────────────────────────────────────────────────────")
        print("  SCHEDULED")
        print("  ─────────────────────────────────────────────────────")
        for b in sorted(blocks, key=lambda x: x.start_time):
            t = task_map.get(b.task_id)
            p_lbl = _PL.get(t.priority, "P?") if t else "P?"
            split_note = f" [part {b.split_part}]" if b.split_session else ""
            print(
                f"\n  {b.start_time.strftime('%H:%M')} – {b.end_time.strftime('%H:%M')}   "
                f"{b.task_name}{split_note}  ({b.duration_minutes}min, {p_lbl})"
            )
            if b.placement_reason:
                reason = textwrap.fill(
                    b.placement_reason, width=50, subsequent_indent="                  "
                )
                print(f"                └─ {reason}")

    if any(
        p.get("reason") != "@waiting — never auto-scheduled" for p in auto_pushed
    ):
        print()
        print("  ─────────────────────────────────────────────────────")
        print("  PUSHED TO LATER")
        print("  ─────────────────────────────────────────────────────")
        for p in auto_pushed:
            if p.get("reason") == "@waiting — never auto-scheduled":
                continue
            suggested = p.get("suggested_date", "")
            date_note = f" → {suggested}:" if suggested else ":"
            print(f"  •  {p['task_name']}{date_note}  {p.get('reason', '')[:60]}")

    # Diff section
    print()
    print("  ─────────────────────────────────────────────────────")
    print("  WHAT CHANGED")
    print("  ─────────────────────────────────────────────────────")

    new_urgent_block = new_by_id.get(new_task.id)
    if new_urgent_block:
        print(f"\n  ➕ ADDED (urgent):")
        print(
            f"     {new_urgent_block.start_time.strftime('%H:%M')}–"
            f"{new_urgent_block.end_time.strftime('%H:%M')}  "
            f"{new_task.content}  "
            f"({new_urgent_block.duration_minutes}min, {_PL.get(new_task.priority, 'P?')})"
        )

    moved_entries = []
    for task_id, orig_row in original_by_id.items():
        if task_id == new_task.id:
            continue
        orig_sched = orig_row.get("scheduled_at")
        if not orig_sched:
            continue
        nb = new_by_id.get(task_id)
        if nb is None:
            continue
        try:
            orig_dt = datetime.fromisoformat(orig_sched)
            if orig_dt.tzinfo is None:
                orig_dt = orig_dt.replace(tzinfo=tz)
            else:
                orig_dt = orig_dt.astimezone(tz)
        except ValueError:
            continue
        delta = int((nb.start_time - orig_dt).total_seconds() / 60)
        if abs(delta) > 1:
            moved_entries.append(
                (orig_row.get("task_name", task_id), orig_dt, nb.start_time, delta)
            )

    if moved_entries:
        print(f"\n  ↔  MOVED:")
        for tname, orig_dt, new_dt, delta in moved_entries:
            direction = f"+{delta}min" if delta > 0 else f"{delta}min"
            print(
                f"     '{tname}'  {orig_dt.strftime('%H:%M')} → "
                f"{new_dt.strftime('%H:%M')}  ({direction})"
            )

    pushed_from_today = [
        p
        for p in auto_pushed
        if p["task_id"] in original_by_id
        and p.get("reason") != "@waiting — never auto-scheduled"
    ]
    if pushed_from_today:
        print(f"\n  ➡  PUSHED TO TOMORROW:")
        for p in pushed_from_today:
            t = task_map.get(p["task_id"])
            dur = t.duration_minutes if t else "?"
            print(f"     '{p['task_name']}'  ({dur}min needed, no room)")

    print()
    print("═" * 57)

    # ── Edge case: urgent task itself didn't fit ──────────────────────────────
    if new_task.id in pushed_ids:
        print(
            f"\n⚠️  Not enough time today for '{new_task.content}' ({new_task.duration_minutes}min)."
        )
        print(f"   Remaining free time: {total_free}min across {len(windows)} window(s).")
        _handle_no_room(client, new_task, target_date, context, tz, events, tz_str)
        return

    # ── STEP 8: Confirmation ──────────────────────────────────────────────────
    try:
        confirm = input("\nConfirm updated schedule? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("Schedule discarded — no changes made.")
        return

    today_dow = target_date.strftime("%A")

    # A) New urgent task
    if new_urgent_block:
        try:
            client.schedule_task(
                new_task.id, new_urgent_block.start_time, new_urgent_block.duration_minutes
            )
        except Exception as exc:
            print(f"[WARN] Could not schedule '{new_task.content}': {exc}")
        insert_task_history(
            task_id=new_task.id,
            task_name=new_task.content,
            project_id=new_task.project_id,
            estimated_duration_mins=new_urgent_block.duration_minutes,
            scheduled_at=new_urgent_block.start_time.isoformat(),
            day_of_week=today_dow,
        )

    # B) Moved tasks
    n_moved = 0
    for task_id, orig_row in original_by_id.items():
        if task_id == new_task.id:
            continue
        nb = new_by_id.get(task_id)
        if nb is None:
            continue
        try:
            client.schedule_task(task_id, nb.start_time, nb.duration_minutes)
        except Exception as exc:
            print(f"[WARN] Could not update '{orig_row.get('task_name', task_id)}': {exc}")
        t = task_map.get(task_id)
        insert_task_history(
            task_id=task_id,
            task_name=orig_row.get("task_name", ""),
            project_id=t.project_id if t else "",
            estimated_duration_mins=nb.duration_minutes,
            scheduled_at=nb.start_time.isoformat(),
            day_of_week=today_dow,
        )
        n_moved += 1

    # C) Pushed to tomorrow
    n_pushed_tomorrow = 0
    for p in pushed_from_today:
        task_id = p["task_id"]
        try:
            client.clear_task_due(task_id)
        except Exception as exc:
            print(f"[WARN] Could not clear due for '{p.get('task_name', task_id)}': {exc}")
        try:
            client.add_comment(
                task_id,
                f"Pushed from {target_date.strftime('%a %b %d')} by emergency insert: {new_task.content}",
            )
        except Exception:
            pass
        delete_task_history_row(task_id, today_str)
        n_pushed_tomorrow += 1

    # D) schedule_log
    insert_schedule_log(
        schedule_date=today_str,
        proposed_json={
            "scheduled": [
                {
                    "task_id": b.task_id,
                    "task_name": b.task_name,
                    "start_time": b.start_time.isoformat(),
                    "duration_minutes": b.duration_minutes,
                }
                for b in blocks
            ],
            "pushed": [
                {"task_id": p["task_id"], "task_name": p["task_name"]}
                for p in auto_pushed
            ],
        },
        confirmed=True,
        confirmed_at=datetime.now().isoformat(),
        replan_trigger="--add-task",
    )

    print(f"\n✅ Schedule updated.")
    if new_urgent_block:
        print(
            f"   {new_task.content}: scheduled "
            f"{new_urgent_block.start_time.strftime('%H:%M')}–{new_urgent_block.end_time.strftime('%H:%M')}"
        )
    if n_moved:
        print(f"   {n_moved} task(s) moved")
    if n_pushed_tomorrow:
        print(f"   {n_pushed_tomorrow} task(s) pushed to tomorrow")


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

  python main.py --sync [DATE]
      Reconcile task_history against Todoist (drift detection).
      Detects manually moved/completed tasks and updates the local DB.
      Called automatically at the start of --review and --plan-day (re-run).

      DATE examples:  (default: today)
        --sync yesterday
        --sync 2026-04-08

  python main.py --add-task "SEARCH TEXT" [--date DATE]
      Insert an urgent task into an already-confirmed plan.
      Searches Todoist for a task matching the text, replans
      everything from the current time forward, and writes back.
      Task must exist in Todoist with a duration label (@30min etc.)

      --date  Target date (default: today)
        --add-task "deploy hotfix"
        --add-task "call with" --date tomorrow

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


def _resolve_target_date(date_arg: str, prefer: str = "future") -> date:
    """
    Resolve an optional date argument to a concrete date.
    Accepts: "" (today), "yesterday", "tomorrow", "monday", "2026-04-07", etc.
    prefer: "future" for --plan-day, "past" for --sync / --review.
    """
    if not date_arg:
        return date.today()

    import dateparser

    parsed = dateparser.parse(
        date_arg,
        settings={
            "PREFER_DATES_FROM": prefer,
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if parsed is None:
        print(f"[ERROR] Could not parse date: '{date_arg}'")
        print("  Examples: yesterday, tomorrow, monday, 2026-04-07")
        sys.exit(1)

    return parsed.date()


def _cmd_sync(context: dict, target_date: date, *, silent: bool = False) -> dict:
    """
    --sync [DATE]: drift detection — reconcile task_history against Todoist.

    Reads Todoist, writes only to local SQLite. No LLM, no Todoist writes.

    Cases:
      A: time moved, same day  → update scheduled_at + reschedule_count
      B: moved to different day (or due cleared) → was_agent_scheduled = 0
      C: 404 (completed/deleted outside --review) → set completed_at
      D: no drift → no-op

    Returns: {"moved": int, "completed_outside": int, "injected": int, "unchanged": int}

    silent=True (auto-called from --review / --plan-day):
      - No changes → print "[Sync] no drift detected"
      - Changes → print per-task lines + one summary line
    silent=False (direct --sync):
      - Always print "[Sync] date — checking N tasks..."
      - No changes → print "[Sync] no drift detected"
      - Changes → print per-task lines + summary
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed as futures_as_completed

    import requests as _requests

    from src.db import (
        append_sync_diff,
        get_task_history_for_sync,
        get_task_ids_for_date,
        setup_database,
        sync_apply_case_a,
        sync_apply_case_b,
        sync_apply_case_c,
        sync_inject_task,
    )
    from src.todoist_client import TodoistClient

    setup_database()

    api_token = os.getenv("TODOIST_API_TOKEN")
    target_str = target_date.isoformat()
    date_label = target_date.strftime("%a %b %-d")

    _tz_aliases = {
        "PST": "America/Vancouver",
        "PST/Vancouver": "America/Vancouver",
        "Vancouver": "America/Vancouver",
    }
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _tz_aliases.get(tz_str, tz_str)
    tz = ZoneInfo(tz_str_norm)

    # ── Step 1: Ground truth from task_history ────────────────────────────────
    rows = get_task_history_for_sync(target_str)
    client = TodoistClient(api_token)

    if rows and not silent:
        print(f"[Sync] {date_label} — checking {len(rows)} task(s)...")

    # ── Steps 2-3: Batch fetch + classify (only when rows exist) ────────────
    fetched: list[tuple[dict, object]] = []

    def _fetch_one(row: dict) -> tuple[dict, "TodoistTask | None | str"]:
        """Returns (row, task|None|'error'|'rate_limited')."""
        for attempt in range(2):
            try:
                task = client.get_task_by_id(row["task_id"])
                return row, task
            except _requests.exceptions.HTTPError as exc:
                if (
                    exc.response is not None
                    and exc.response.status_code == 429
                    and attempt == 0
                ):
                    time.sleep(1)
                    continue
                if (
                    exc.response is not None
                    and exc.response.status_code == 429
                ):
                    print(
                        f"  [Sync][WARN] rate limited on"
                        f" '{row.get('task_name', row['task_id'])}', skipping"
                    )
                    return row, "rate_limited"
                return row, "error"
            except Exception:
                return row, "error"
        return row, "error"

    if rows:
        with ThreadPoolExecutor(max_workers=4) as executor:
            fs = [executor.submit(_fetch_one, row) for row in rows]
            for future in futures_as_completed(fs):
                fetched.append(future.result())

    # ── Step 3: Classify into Cases A / B / C / D ────────────────────────────
    n_moved = 0
    n_completed_outside = 0
    n_unchanged = 0
    diff_changes: list[dict] = []

    for row, result in fetched:
        task_name = row.get("task_name") or row["task_id"]
        scheduled_at = row.get("scheduled_at")

        if result in ("error", "rate_limited"):
            continue  # warning already printed in _fetch_one

        # Already reviewed (completed_at set by --review) — treat as D
        if row.get("completed_at") is not None:
            n_unchanged += 1
            continue

        if result is None:
            # Case C: 404 → completed or deleted outside --review
            completed_now = datetime.now(tz).isoformat()
            sync_apply_case_c(row["task_id"], target_str, completed_now)
            print(f"  \u2713  {task_name}: completed outside review (duration unknown)")
            n_completed_outside += 1
            diff_changes.append({"task_id": row["task_id"], "case": "C", "task_name": task_name})
            continue

        # result is a TodoistTask
        task = result  # type: ignore[assignment]
        todoist_dt = task.due_datetime  # tz-aware or None

        if todoist_dt is None:
            # No due_datetime at all → treat as Case B (unscheduled)
            sync_apply_case_b(row["task_id"], target_str)
            print(f"  \u2192  {task_name}: due date cleared (unscheduled)")
            n_moved += 1
            diff_changes.append({
                "task_id": row["task_id"], "case": "B",
                "task_name": task_name, "to": None,
            })
            continue

        # Normalise to user's timezone for date/time comparison
        if todoist_dt.tzinfo is None:
            todoist_local = todoist_dt.replace(tzinfo=tz)
        else:
            todoist_local = todoist_dt.astimezone(tz)

        todoist_date = todoist_local.date()

        if todoist_date != target_date:
            # Case B: moved to a different day
            sync_apply_case_b(row["task_id"], target_str)
            new_date_str = todoist_date.strftime("%a %b %-d")
            print(f"  \u2192  {task_name}: moved to {new_date_str}")
            n_moved += 1
            diff_changes.append({
                "task_id": row["task_id"], "case": "B",
                "task_name": task_name, "to": todoist_date.isoformat(),
            })
            continue

        # Same day — check 5-minute drift
        if not scheduled_at:
            n_unchanged += 1
            continue

        try:
            sched_dt = datetime.fromisoformat(scheduled_at)
            if sched_dt.tzinfo is None:
                sched_local = sched_dt.replace(tzinfo=tz)
            else:
                sched_local = sched_dt.astimezone(tz)

            diff_mins = abs((todoist_local - sched_local).total_seconds() / 60)

            if diff_mins > 5:
                # Case A: time moved, same day
                from_str = sched_local.strftime("%H:%M")
                to_str = todoist_local.strftime("%H:%M")
                sync_apply_case_a(row["task_id"], target_str, todoist_local.isoformat())
                print(f"  \u2194  {task_name}: moved {from_str} \u2192 {to_str}")
                n_moved += 1
                diff_changes.append({
                    "task_id": row["task_id"], "case": "A",
                    "task_name": task_name, "from": from_str, "to": to_str,
                })
            else:
                # Case D: no drift
                n_unchanged += 1
        except (ValueError, TypeError):
            n_unchanged += 1

    # ── Step 4: Detect user-injected tasks ────────────────────────────────────
    n_injected = 0
    try:
        todoist_tasks = client.get_todays_scheduled_tasks(target_date)
        known_ids = get_task_ids_for_date(target_str)

        for task in todoist_tasks:
            if task.id in known_ids or task.due_datetime is None:
                continue
            scheduled_iso = task.due_datetime.astimezone(tz).isoformat()
            sync_inject_task(
                task_id=task.id,
                task_name=task.content,
                project_id=task.project_id or "",
                estimated_duration_mins=task.duration_minutes,
                scheduled_at=scheduled_iso,
            )
            print(
                f"  +  {task.content}: user-scheduled (not agent-planned),"
                " added to history"
            )
            n_injected += 1
            diff_changes.append({
                "task_id": task.id, "case": "inject", "task_name": task.content,
            })
    except Exception as exc:
        print(f"  [Sync][WARN] Could not scan for user-injected tasks: {exc}")

    # ── Step 5: Write audit trail + print summary ─────────────────────────────
    if diff_changes:
        try:
            append_sync_diff(target_str, diff_changes)
        except Exception:
            pass  # audit trail write failure is non-fatal

    counts = {
        "moved": n_moved,
        "completed_outside": n_completed_outside,
        "injected": n_injected,
        "unchanged": n_unchanged,
    }

    no_drift = n_moved == 0 and n_completed_outside == 0 and n_injected == 0

    if not rows and no_drift:
        if not silent:
            print(f"[Sync] No scheduled tasks found for {target_str}.")
    elif no_drift:
        print("[Sync] no drift detected")
    else:
        parts = []
        if n_moved:
            parts.append(f"{n_moved} moved")
        if n_completed_outside:
            parts.append(f"{n_completed_outside} completed outside review")
        if n_injected:
            parts.append(f"{n_injected} injected")
        if n_unchanged:
            parts.append(f"{n_unchanged} unchanged")
        print(f"[Sync] {', '.join(parts)}")

    return counts


def _cmd_plan_day(context: dict, target_date: date) -> None:
    """
    --plan-day [DATE]: filter → enrich → confirm priorities → schedule → display → write-back.
    Read-only except for optional priority writes in Step C and confirmed write-back in Step F.
    """
    from src.calendar_client import get_events
    from src.db import (
        get_task_history_for_sync,
        insert_schedule_log,
        insert_task_history,
        setup_database,
    )
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

    # Auto-sync if re-running plan-day for a date that already has a schedule
    _existing_for_sync = get_task_history_for_sync(target_date.isoformat())
    if _existing_for_sync:
        print("[Sync] Existing schedule detected — checking for drift...")
        _cmd_sync(context, target_date, silent=True)
        print()

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

    # ── Detect mid-day replanning ──────────────────────────────────────────────
    # When planning today and the morning peak has already passed, the LLM needs
    # to know so it doesn't propose morning-based placements.
    schedule_context = context  # default; overridden below if mid-day
    if target_date == date.today() and windows:
        _tz_local = ZoneInfo(_tz_str_norm)
        _now = datetime.now(tz=_tz_local)
        _ft = context.get("sleep", {}).get("first_task_not_before", "10:30")
        _fth, _ftm = map(int, _ft.split(":"))
        _morning_cutoff = datetime(
            target_date.year, target_date.month, target_date.day, _fth, _ftm,
            tzinfo=_tz_local,
        )
        if _now > _morning_cutoff:
            hours_passed = (_now - _morning_cutoff).total_seconds() / 3600
            print(
                f"[Scheduler] Mid-day plan: starting from {windows[0].start.strftime('%H:%M')} "
                f"({hours_passed:.1f}h of morning already passed)"
            )
            _midday_rule = (
                f"NOTE: It is currently {_now.strftime('%H:%M')}. The morning peak window has "
                f"passed. Schedule from the afternoon secondary peak onwards. Do not reference "
                f"morning productivity windows — they are no longer available."
            )
            schedule_context = {
                **context,
                "rules": {
                    "hard": list(context.get("rules", {}).get("hard", [])) + [_midday_rule],
                    "soft": list(context.get("rules", {}).get("soft", [])),
                },
            }

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
        context=schedule_context,
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
    _ftb = context.get("sleep", {}).get("first_task_not_before", "10:30")
    for block in blocks:
        if block.split_part == 2:
            continue  # don't double-log split tasks
        original = task_map.get(block.task_id)
        enr = enriched_by_id.get(block.task_id, {})
        was_dw = int("deep-work" in (original.labels if original else []))
        pre_mtg = int(_has_pre_meeting(block, events, context))
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
            was_deep_work=was_dw,
            back_to_back=int(block.back_to_back),
            pre_meeting=pre_mtg,
            sync_source="agent",
            was_agent_scheduled=1,
            first_task_not_before=_ftb,
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
        compute_quality_score,
        get_todays_task_history,
        insert_task_history,
        mark_task_partial,
        mark_task_rescheduled_externally,
        set_incomplete_reason,
        setup_database,
        update_quality_score,
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

    # ── Auto-sync: reconcile before review ────────────────────────────────────
    _cmd_sync(context, target_date, silent=True)

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

        _REASON_MAP = {"1": "time", "2": "motivation", "3": "blocked", "4": "skipped"}

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

        else:
            # Capture incomplete reason before deciding progress bucket
            try:
                print(
                    "     Why? [1] Ran out of time  [2] Lost motivation  "
                    "[3] Externally blocked  [4] Didn't attempt"
                )
                r_choice = input("     > ").strip()
            except (EOFError, KeyboardInterrupt):
                r_choice = ""
            _reason = _REASON_MAP.get(r_choice)
            set_incomplete_reason(row["task_id"], _reason)

            if choice == "1" or choice not in ("2", "3", "4"):
                print()
                incomplete_with_remaining.append((row, task, est, "not_started"))

            else:  # choice in ("2", "3", "4")
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

    # ── Quality score — computed HERE, before reschedule writes change scheduled_at ──
    # Must run after Step 3 (so completed_at is set for done tasks) but before
    # reschedule writes (which upsert scheduled_at to tomorrow, removing rescheduled
    # tasks from today's dataset and inflating the score).
    quality = compute_quality_score(target_str)
    update_quality_score(target_str, quality)

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
                candidate = target_date + timedelta(days=days_ahead)
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
                if cand_date == today:
                    day_label = "Today"
                elif cand_date == today + timedelta(days=1):
                    day_label = "Tomorrow"
                else:
                    day_label = cand_date.strftime("%a %b %d")
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
    print(f"  Schedule quality: {quality:.0f}/100")
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
    parser.add_argument("--sync", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--add-task", type=str, metavar="TASK")
    parser.add_argument("--date", type=str, metavar="DATE", default=None,
                        help="Target date for --add-task (default: today)")

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
        target_date = _resolve_target_date(args.review, prefer="past")
        _cmd_review(context, target_date)
    elif args.sync is not None:
        target_date = _resolve_target_date(args.sync, prefer="past")
        _cmd_sync(context, target_date, silent=False)
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
        add_task_date = _resolve_target_date(args.date) if args.date else date.today()
        _cmd_add_task(context, args.add_task, add_task_date)
    else:
        _print_help()


if __name__ == "__main__":
    main()
