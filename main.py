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
from datetime import date
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
  python main.py --onboard
      Set up your scheduling config from your calendar.
      Stage 1: Scans 14 days of Google Calendar, detects patterns
               (wake time, color semantics, recurring blocks), and
               proposes a draft context.json via LLM.
      Stage 2: Interactive Q&A to refine uncertain values.
      Stage 3: Schedule audit — review and object to placements.

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
    parser.add_argument("--onboard", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--plan-day", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--review", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--sync", nargs="?", const="", default=None, metavar="DATE")
    parser.add_argument("--status", action="store_true")
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

    if args.onboard:
        from src.commands.onboard import cmd_onboard
        cmd_onboard(context)
    elif args.check:
        from src.commands.check import cmd_check
        cmd_check(context)
    elif args.plan_day is not None:
        from src.commands.plan import cmd_plan_day
        target_date = _resolve_target_date(args.plan_day)
        cmd_plan_day(context, target_date)
    elif args.review is not None:
        from src.commands.review import cmd_review
        target_date = _resolve_target_date(args.review, prefer="past")
        cmd_review(context, target_date)
    elif args.sync is not None:
        from src.commands.sync import cmd_sync
        target_date = _resolve_target_date(args.sync, prefer="past")
        cmd_sync(context, target_date, silent=False)
    elif args.status:
        from src.commands.status import cmd_status
        cmd_status(context)
    elif args.add_project:
        if args.budget is None:
            print("[ERROR] --add-project requires --budget HOURS")
            sys.exit(1)
        from src.commands.projects import cmd_add_project
        cmd_add_project(context, args)
    elif args.update_project:
        from src.commands.projects import cmd_update_project
        cmd_update_project(context, args)
    elif args.projects:
        from src.commands.projects import cmd_projects
        cmd_projects(context)
    elif args.unplan is not None:
        from src.commands.unplan import cmd_unplan
        target_date = _resolve_target_date(args.unplan)
        cmd_unplan(context, target_date, args.task)
    elif args.delete_project:
        from src.commands.projects import cmd_delete_project
        cmd_delete_project(context, args)
    elif args.reset_project:
        from src.commands.projects import cmd_reset_project
        cmd_reset_project(context, args)
    elif args.add_task:
        from src.commands.add_task import cmd_add_task
        add_task_date = _resolve_target_date(args.date) if args.date else date.today()
        cmd_add_task(context, args.add_task, add_task_date)
    else:
        _print_help()


if __name__ == "__main__":
    main()
