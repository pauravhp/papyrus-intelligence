"""--review command: interactive end-of-day review."""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.calendar_client import get_events
from src.db import setup_database
from src.models import TodoistTask
from src.queries import (
    compute_quality_score,
    decrement_budget,
    get_all_active_budgets,
    get_todays_task_history,
    insert_task_history,
    mark_task_partial,
    mark_task_rescheduled_externally,
    set_incomplete_reason,
    update_quality_score,
    upsert_task_completed,
)
from src.scheduler import compute_free_windows
from src.sync_engine import run_sync
from src.todoist_client import TodoistClient

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def cmd_review(context: dict, target_date: date) -> None:
    """
    --review [DATE]: hybrid source of truth.

    task_history tells us WHICH tasks to review.
    Todoist (get_task_by_id) tells us the STATUS of each task.
    """
    setup_database()

    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _TZ_ALIASES.get(tz_str, tz_str)
    tz = ZoneInfo(tz_str_norm)
    extra_cal_ids = context.get("calendar_ids", [])

    today = date.today()
    target_str = target_date.isoformat()
    now_iso = datetime.now(tz).isoformat()

    api_token = os.getenv("TODOIST_API_TOKEN")
    client = TodoistClient(api_token)

    # ── Auto-sync: reconcile before review ────────────────────────────────────
    run_sync(context, target_date, silent=True)

    # ── Step 1: Load from task_history ────────────────────────────────────────
    print(f"\n[Review] Loading tasks for {target_str} from task_history...")
    rows = get_todays_task_history(target_str)
    if not rows:
        print(f"  No tasks were scheduled via --plan-day for {target_str}.")
        print(f"  Run: python main.py --plan-day {target_str}")
        return

    print(f"  {len(rows)} planned task(s) found\n")

    # ── Step 2: Check each task status via Todoist ────────────────────────────
    n_auto_completed = 0
    n_external = 0
    incomplete: list[tuple[dict, TodoistTask]] = []

    for row in rows:
        task = client.get_task_by_id(row["task_id"])

        if task is None:
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
            new_date = task.due_datetime.astimezone(tz).date()
            print(
                f"  \U0001f4c5 {row['task_name']} (rescheduled externally to {new_date}) \u2014 skipping"
            )
            mark_task_rescheduled_externally(row["task_id"])
            n_external += 1

        else:
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

            else:
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

    # ── Quality score ─────────────────────────────────────────────────────────
    quality = compute_quality_score(target_str)
    update_quality_score(target_str, quality)

    # ── Step 4: Reschedule incomplete tasks ───────────────────────────────────
    to_reschedule = [
        (row, task, rem, st)
        for row, task, rem, st in incomplete_with_remaining
        if st != "done"
    ]

    proposals: list[
        tuple[dict, int, "date | None", "datetime | None", "datetime | None"]
    ] = []
    session_tasks_by_day: dict[date, list[TodoistTask]] = {}

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
                        candidate, tz_str, calendar_ids=extra_cal_ids
                    )
                except Exception:
                    events = []

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
                                    ) or 30,
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
