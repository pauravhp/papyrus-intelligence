"""
Revert the most recent confirmed schedule for a user — testing utility.

Usage:
    python3 scripts/revert_schedule.py --user-id <uuid> [--date YYYY-MM-DD] [--dry-run]

Reads the most recent confirmed schedule_log row for the user (optionally
scoped to a specific schedule_date), then:
  1. Deletes the GCal events listed in gcal_event_ids
  2. Clears due_datetime + duration on every real Todoist task that was scheduled
  3. Deletes the schedule_log row

Skips rhythm entries (task_id starting with "proj_") — they never had a
due_datetime set in Todoist (see Rule 5 in CLAUDE.md).

Env required (from .env or ambient):
    SUPABASE_URL, SUPABASE_SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make sibling packages importable when running from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.calendar_client import build_gcal_service_from_credentials, delete_event
from src.todoist_client import TodoistClient


def _supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SECRET_KEY"]
    return create_client(url, key)


def _load_user(sb, user_id: str) -> dict:
    row = (
        sb.from_("users")
        .select("google_credentials, todoist_oauth_token")
        .eq("id", user_id)
        .single()
        .execute()
    )
    if not row.data:
        raise SystemExit(f"No user row for id={user_id}")
    return row.data


def _load_latest_schedule(sb, user_id: str, target_date: str | None) -> dict | None:
    q = (
        sb.from_("schedule_log")
        .select("id, schedule_date, proposed_json, gcal_event_ids, gcal_write_calendar_id, confirmed_at")
        .eq("user_id", user_id)
        .eq("confirmed", 1)
    )
    if target_date:
        q = q.eq("schedule_date", target_date)
    result = q.order("confirmed_at", desc=True).limit(1).execute()
    return (result.data or [None])[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-id", required=True, help="Supabase user UUID")
    ap.add_argument("--date", default=None, help="Schedule date YYYY-MM-DD (optional — defaults to latest)")
    ap.add_argument("--dry-run", action="store_true", help="Print what would happen; don't write")
    args = ap.parse_args()

    sb = _supabase()
    user = _load_user(sb, args.user_id)
    schedule = _load_latest_schedule(sb, args.user_id, args.date)
    if not schedule:
        print(f"No confirmed schedule_log row found for user {args.user_id}" + (f" on {args.date}" if args.date else ""))
        return 1

    print(f"Reverting schedule_log row id={schedule['id']} date={schedule['schedule_date']} confirmed_at={schedule.get('confirmed_at')}")

    gcal_event_ids = json.loads(schedule.get("gcal_event_ids") or "[]")
    write_cal_id = schedule.get("gcal_write_calendar_id") or "primary"
    proposed = json.loads(schedule.get("proposed_json") or "{}")
    scheduled = proposed.get("scheduled") or []
    real_task_ids = [s["task_id"] for s in scheduled if not s.get("task_id", "").startswith("proj_")]

    print(f"  → {len(gcal_event_ids)} GCal events to delete on calendar {write_cal_id}")
    print(f"  → {len(real_task_ids)} Todoist tasks to clear due_datetime")

    if args.dry_run:
        print("Dry run — no writes performed.")
        return 0

    # GCal deletions
    gcal_creds = user.get("google_credentials")
    if gcal_creds and gcal_event_ids:
        from api.config import settings
        svc, refreshed = build_gcal_service_from_credentials(
            gcal_creds, settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        )
        if refreshed:
            sb.from_("users").update({"google_credentials": refreshed}).eq("id", args.user_id).execute()
        deleted = 0
        for eid in gcal_event_ids:
            try:
                delete_event(svc, eid, calendar_id=write_cal_id)
                deleted += 1
            except Exception as exc:
                print(f"    ! delete {eid} failed: {exc}")
        print(f"  ✓ GCal: deleted {deleted}/{len(gcal_event_ids)}")
    elif gcal_event_ids:
        print("  ! No google_credentials on user row — skipping GCal deletions")

    # Todoist clears
    tod_tok = (user.get("todoist_oauth_token") or {}).get("access_token")
    if tod_tok and real_task_ids:
        client = TodoistClient(tod_tok)
        cleared = 0
        for tid in real_task_ids:
            try:
                client.clear_task_schedule(tid)
                cleared += 1
            except Exception as exc:
                print(f"    ! clear {tid} failed: {exc}")
        print(f"  ✓ Todoist: cleared {cleared}/{len(real_task_ids)}")
    elif real_task_ids:
        print("  ! No todoist_oauth_token on user row — skipping Todoist clears")

    # schedule_log row
    sb.from_("schedule_log").delete().eq("id", schedule["id"]).execute()
    print(f"  ✓ schedule_log row {schedule['id']} deleted")
    print("Revert complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
