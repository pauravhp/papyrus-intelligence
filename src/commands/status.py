"""--status command: show today's schedule summary."""

from datetime import date

from src.db import setup_database
from src.queries import compute_quality_score, get_todays_task_history


def cmd_status(context: dict) -> None:
    """--status: print a brief summary of today's confirmed schedule."""
    setup_database()
    today_str = date.today().isoformat()
    rows = get_todays_task_history(today_str)

    if not rows:
        print(f"\n[Status] No confirmed schedule for today ({today_str}).")
        print("  Run --plan-day to schedule your day.\n")
        return

    quality = compute_quality_score(today_str)
    completed = sum(1 for r in rows if r.get("completed_at"))
    remaining = len(rows) - completed

    print(f"\n[Status] {today_str}")
    print(f"  Tasks planned:    {len(rows)}")
    print(f"  Completed:        {completed}")
    print(f"  Remaining:        {remaining}")
    if quality > 0:
        print(f"  Schedule quality: {quality:.0f}/100")
    else:
        print("  Schedule quality: (run --review to compute)")
    print()
