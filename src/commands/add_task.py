"""--add-task command: insert urgent task into an already-confirmed plan."""

import json
import os
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.calendar_client import get_events
from src.llm import enrich_tasks, generate_schedule
from src.models import TodoistTask
from src.queries import (
    delete_task_history_row,
    get_all_active_budgets,
    get_task_history_for_replan,
    insert_schedule_log,
    insert_task_history,
)
from src.schedule_pipeline import build_enriched_task_details
from src.scheduler import compute_free_windows, pack_schedule
from src.todoist_client import TodoistClient

_PL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def _handle_no_room(
    client: TodoistClient,
    new_task: TodoistTask,
    target_date: date,
    context: dict,
    tz: ZoneInfo,
    events: list,
    tz_str: str,
) -> None:
    """Offer options when the urgent task doesn't fit anywhere today."""
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
        tomorrow_events = get_events(
            tomorrow, tz_str, calendar_ids=context.get("calendar_ids", [])
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


def cmd_add_task(context: dict, search_text: str, target_date: date) -> None:
    """--add-task SEARCH_TEXT [--date DATE]: insert urgent task, replan rest of day."""
    tz_str = context.get("user", {}).get("timezone", "America/Vancouver")
    tz_str_norm = _TZ_ALIASES.get(tz_str, tz_str)
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
            target_date, tz_str, calendar_ids=context.get("calendar_ids", [])
        )
        print(f"[GCal] {len(events)} event(s)")
    except Exception as exc:
        print(f"[WARN] GCal fetch failed: {exc}")

    blocked_tasks: list[TodoistTask] = []
    for row in already_done:
        if row.get("scheduled_at") and row.get("estimated_duration_mins"):
            try:
                dt = datetime.fromisoformat(row["scheduled_at"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
            except ValueError:
                continue
            blocked_tasks.append(
                TodoistTask(
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
    replan_tasks: list[TodoistTask] = []
    for row in to_replan:
        t = client.get_task_by_id(row["task_id"])
        if t is not None:
            replan_tasks.append(t)

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
                # Budget record not found — include as a regular task so pack_schedule
                # assigns it a new slot and write-back updates Todoist. Silently dropping
                # it leaves the task holding its old slot while another task overwrites it.
                replan_tasks.append(bt)
                continue
            smin, smax = b["session_min_minutes"], b["session_max_minutes"]
            session_dur = min(smax, largest_w) if largest_w > 0 else smin
            replan_tasks.append(
                TodoistTask(
                    id=bt.id,
                    content=b["project_name"],
                    project_id="",
                    priority=b.get("priority", 3),
                    due_datetime=None,
                    deadline=b.get("deadline"),
                    duration_minutes=session_dur,
                    labels=["deep-work"],
                    is_inbox=False,
                    is_rhythm=True,
                )
            )

    all_schedulable = [new_task] + replan_tasks

    # ── STEP 6: LLM chain ─────────────────────────────────────────────────────
    if not windows:
        print(
            f"\n⚠️  Not enough time today for '{new_task.content}' ({new_task.duration_minutes}min)."
        )
        print(f"   Remaining free time: 0min across 0 windows.")
        _handle_no_room(client, new_task, target_date, context, tz, events, tz_str)
        return

    prod_science_path = Path(__file__).parent.parent.parent / "productivity_science.json"
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
    enriched_with_details = build_enriched_task_details(all_schedulable, enriched_map, _PL)

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

    # D) Safety-net: clear Todoist due for any to_replan task that was neither
    # placed in blocks nor explicitly pushed. Without this, a task that fell
    # through (e.g., budget record missing) keeps its stale Todoist slot while
    # a different task has been written to the same time — causing a collision.
    handled_ids = (
        {new_task.id}
        | set(new_by_id.keys())
        | {p["task_id"] for p in pushed_from_today}
    )
    for task_id, orig_row in original_by_id.items():
        if task_id in handled_ids:
            continue
        try:
            client.clear_task_due(task_id)
        except Exception:
            pass
        try:
            delete_task_history_row(task_id, today_str)
        except Exception:
            pass

    # E) schedule_log
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
