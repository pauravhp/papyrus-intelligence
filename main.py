#!/usr/bin/env python3
"""
Scheduling Agent — CLI entry point.

Usage:
  python main.py --check        Validate the full data pipeline (no LLM)
  python main.py --plan-day     Run scheduling pipeline (Phase 1+)
  python main.py --review       Review pushed/flagged tasks (Phase 2+)
  python main.py --add-task     Add a task to Todoist inbox
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv


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
        events = get_events(today, tz_str)
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
        yesterday_events = get_events(yesterday, tz_str)
        for ev in yesterday_events:
            if not ev.is_all_day and ev.end.hour >= 23:
                late_night_prior = True
                print(
                    f"[GCal] Late night detected: '{ev.summary}' ended at "
                    f"{ev.end.strftime('%H:%M')} yesterday — morning buffer extended"
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
        windows = compute_free_windows(events, today, context, late_night_prior=late_night_prior)
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Scheduling Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true",
                        help="Validate data pipeline end-to-end (no LLM)")
    parser.add_argument("--plan-day", action="store_true",
                        help="Run full scheduling pipeline (Phase 1+)")
    parser.add_argument("--review", action="store_true",
                        help="Review pushed/flagged tasks (Phase 2+)")
    parser.add_argument("--add-task", type=str, metavar="TASK",
                        help="Add a task to Todoist inbox")
    args = parser.parse_args()

    context = _load_config()

    if args.check:
        _cmd_check(context)
    elif args.plan_day:
        print("[ERROR] --plan-day not yet implemented (Phase 1)")
        sys.exit(1)
    elif args.review:
        print("[ERROR] --review not yet implemented (Phase 2)")
        sys.exit(1)
    elif args.add_task:
        print("[ERROR] --add-task not yet implemented")
        sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
