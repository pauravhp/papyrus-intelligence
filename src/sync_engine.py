"""
Core sync logic — reconcile task_history against Todoist (drift detection).

Called by src/commands/sync.py (direct --sync) and by plan/review commands
(auto-sync with silent=True). No command file imports this module — commands
import from src/ directly per the architecture rule.

Cases:
  A: time moved, same day  → update scheduled_at + reschedule_count
  B: moved to different day (or due cleared) → was_agent_scheduled = 0
  C: 404 (completed/deleted outside --review) → set completed_at
  D: no drift → no-op

Returns: {"moved": int, "completed_outside": int, "injected": int, "unchanged": int}
"""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed as futures_as_completed
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests as _requests

from src.db import setup_database
from src.queries import (
    append_sync_diff,
    get_task_history_for_sync,
    get_task_ids_for_date,
    get_user_injected_for_deletion_check,
    sync_apply_case_a,
    sync_apply_case_b,
    sync_apply_case_c,
    sync_inject_task,
)
from src.todoist_client import TodoistClient

_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def run_sync(context: dict, target_date: date, *, silent: bool = False) -> dict:
    """
    Reconcile task_history against Todoist for target_date.

    silent=True: prints per-task change lines + summary only when changes exist.
    silent=False: always prints header, always prints outcome.
    """
    setup_database()

    import os
    api_token = os.getenv("TODOIST_API_TOKEN")
    target_str = target_date.isoformat()
    date_label = target_date.strftime("%a %b %-d")

    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _TZ_ALIASES.get(tz_str, tz_str)
    tz = ZoneInfo(tz_str_norm)

    # ── Step 1: Ground truth from task_history ────────────────────────────────
    rows = get_task_history_for_sync(target_str)
    client = TodoistClient(api_token)

    if rows and not silent:
        print(f"[Sync] {date_label} — checking {len(rows)} task(s)...")

    # ── Steps 2-3: Batch fetch + classify (only when rows exist) ──────────────
    fetched: list[tuple[dict, object]] = []

    def _fetch_one(row: dict) -> tuple[dict, object]:
        """Returns (row, task|None|'error'|'rate_limited')."""
        for attempt in range(2):
            try:
                task = client.get_task_by_id(row["task_id"])
                return row, task
            except _requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status == 429 and attempt == 0:
                    time.sleep(1)
                    continue
                if status == 429:
                    print(
                        f"  [Sync][WARN] rate limited on"
                        f" '{row.get('task_name', row['task_id'])}', skipping"
                    )
                    return row, "rate_limited"
                # 404/410: task gone (deleted or completed) — treat as Case C.
                # get_task_by_id handles 404 internally, but 410 (Gone) would
                # fall through to raise_for_status() and land here instead.
                if status in (404, 410):
                    return row, None
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
            continue

        if row.get("completed_at") is not None:
            n_unchanged += 1
            continue

        if result is None:
            completed_now = datetime.now(tz).isoformat()
            sync_apply_case_c(row["task_id"], target_str, completed_now)
            print(f"  \u2713  {task_name}: completed outside review (duration unknown)")
            n_completed_outside += 1
            diff_changes.append({"task_id": row["task_id"], "case": "C", "task_name": task_name})
            continue

        task = result
        todoist_dt = task.due_datetime

        if todoist_dt is None:
            sync_apply_case_b(row["task_id"], target_str)
            print(f"  \u2192  {task_name}: due date cleared (unscheduled)")
            n_moved += 1
            diff_changes.append({"task_id": row["task_id"], "case": "B", "task_name": task_name, "to": None})
            continue

        if todoist_dt.tzinfo is None:
            todoist_local = todoist_dt.replace(tzinfo=tz)
        else:
            todoist_local = todoist_dt.astimezone(tz)

        todoist_date = todoist_local.date()

        if todoist_date != target_date:
            sync_apply_case_b(row["task_id"], target_str)
            new_date_str = todoist_date.strftime("%a %b %-d")
            print(f"  \u2192  {task_name}: moved to {new_date_str}")
            n_moved += 1
            diff_changes.append({"task_id": row["task_id"], "case": "B", "task_name": task_name, "to": todoist_date.isoformat()})
            continue

        if not scheduled_at:
            n_unchanged += 1
            continue

        try:
            sched_dt = datetime.fromisoformat(scheduled_at)
            sched_local = sched_dt.astimezone(tz) if sched_dt.tzinfo else sched_dt.replace(tzinfo=tz)
            diff_mins = abs((todoist_local - sched_local).total_seconds() / 60)

            if diff_mins > 5:
                from_str = sched_local.strftime("%H:%M")
                to_str = todoist_local.strftime("%H:%M")
                sync_apply_case_a(row["task_id"], target_str, todoist_local.isoformat())
                print(f"  \u2194  {task_name}: moved {from_str} \u2192 {to_str}")
                n_moved += 1
                diff_changes.append({"task_id": row["task_id"], "case": "A", "task_name": task_name, "from": from_str, "to": to_str})
            else:
                n_unchanged += 1
        except (ValueError, TypeError):
            n_unchanged += 1

    # ── Step 4: Deletion check for user-injected tasks ───────────────────────
    # User-injected rows (was_agent_scheduled=0) are excluded from the main
    # agent-row sync loop. Check them separately for deletion only — no Case
    # A/B drift detection since they move freely. Run BEFORE Step 5 (injection
    # scan) so newly-injected tasks aren't immediately flagged as deleted.
    try:
        user_rows = get_user_injected_for_deletion_check(target_str)
        for urow in user_rows:
            utask = client.get_task_by_id(urow["task_id"])
            if utask is None:
                completed_now = datetime.now(tz).isoformat()
                sync_apply_case_c(urow["task_id"], target_str, completed_now)
                uname = urow.get("task_name") or urow["task_id"]
                print(f"  \u2713  {uname}: deleted (user-scheduled task removed)")
                n_completed_outside += 1
                diff_changes.append({"task_id": urow["task_id"], "case": "C", "task_name": uname})
    except Exception as exc:
        if not silent:
            print(f"  [Sync][WARN] Could not check user-injected tasks for deletion: {exc}")

    # ── Step 5: Detect newly user-injected tasks ──────────────────────────────
    n_injected = 0
    try:
        todoist_tasks = client.get_todays_scheduled_tasks(target_date)
        known_ids = get_task_ids_for_date(target_str)

        for task in todoist_tasks:
            if task.id in known_ids or task.due_datetime is None:
                continue
            task_local = (
                task.due_datetime.astimezone(tz)
                if task.due_datetime.tzinfo
                else task.due_datetime.replace(tzinfo=tz)
            )
            if task_local.date() != target_date:
                continue
            was_inserted = sync_inject_task(
                task_id=task.id,
                task_name=task.content,
                project_id=task.project_id or "",
                estimated_duration_mins=task.duration_minutes,
                scheduled_at=task_local.isoformat(),
            )
            if was_inserted:
                print(
                    f"  +  {task.content}: user-scheduled (not agent-planned),"
                    " added to history"
                )
                n_injected += 1
                diff_changes.append({"task_id": task.id, "case": "inject", "task_name": task.content})
    except Exception as exc:
        print(f"  [Sync][WARN] Could not scan for user-injected tasks: {exc}")

    # ── Step 6: Write audit trail + print summary ─────────────────────────────
    if diff_changes:
        try:
            append_sync_diff(target_str, diff_changes)
        except Exception:
            pass

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
