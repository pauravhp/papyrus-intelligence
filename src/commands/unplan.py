"""--unplan command: undo a confirmed --plan-day run."""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.db import setup_database
from src.queries import (
    delete_schedule_log_for_date,
    delete_task_history_row,
    get_task_history_for_date,
)
from src.todoist_client import TodoistClient

_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def cmd_unplan(context: dict, target_date: date, task_filter: str | None) -> None:
    """--unplan [DATE] [--task NAME]: undo a confirmed --plan-day run."""
    setup_database()

    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz = ZoneInfo(_TZ_ALIASES.get(tz_str, tz_str))

    date_str = target_date.isoformat()
    rows = get_task_history_for_date(date_str)

    if not rows:
        print(f"No confirmed plan found for {date_str}.")
        return

    # ── Apply --task filter if provided ───────────────────────────────────────
    single_task_mode = task_filter is not None
    if single_task_mode:
        needle = task_filter.lower()
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
    client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))
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
