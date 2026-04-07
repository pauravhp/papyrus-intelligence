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

from dotenv import load_dotenv

# Model names mirrored here for display in progress messages
ENRICH_MODEL = "llama-3.3-70b-versatile"
SCHEDULE_MODEL = "llama-3.3-70b-versatile"


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
        yesterday_events = get_events(
            yesterday, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        )
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
        for ev in get_events(
            day_before, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        ):
            if not ev.is_all_day and ev.end.hour >= 23:
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

    if not schedulable:
        print("\n[INFO] No unscheduled tasks to plan. Exiting.")
        return

    print(f"\n[Scheduler] {len(schedulable)} schedulable task(s) continuing to LLM…")

    # task_map covers all tasks so pushed/flagged lookups still work for display
    task_map = {t.id: t for t in tasks}

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

        elif task.due_datetime and task.due_datetime.astimezone(tz).date() != target_date:
            # B) Externally rescheduled
            new_date = task.due_datetime.astimezone(tz).date()
            print(f"  \U0001f4c5 {row['task_name']} (rescheduled externally to {new_date}) \u2014 skipping")
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
            print(f"  Ext. moved:   {n_external} task(s) (rescheduled in Todoist directly)")
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

        reschedule_ctx = f"  (rescheduled {reschedule_count} times)" if reschedule_count > 1 else ""
        print(f'  \u274c "{row["task_name"]}"  (estimated: {est}min, {p_str}{reschedule_ctx})')
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
    proposals: list[tuple[dict, int, "date | None", "datetime | None", "datetime | None"]] = []
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
                    events = get_events(candidate, tz_str, extra_calendar_ids=extra_cal_ids)
                except Exception:
                    events = []

                # Use task_history as the source of already-blocked time.
                # This prevents proposing slots that --plan-day has already filled.
                db_rows = get_todays_task_history(candidate_str_inner)
                db_blocked: list[TodoistTask] = []
                for db_row in db_rows:
                    if db_row.get("scheduled_at"):
                        try:
                            sched_dt = datetime.fromisoformat(db_row["scheduled_at"]).astimezone(tz)
                            db_blocked.append(
                                TodoistTask(
                                    id=db_row["task_id"],
                                    content=db_row["task_name"],
                                    project_id=db_row.get("project_id", ""),
                                    priority=1,
                                    due_datetime=sched_dt,
                                    deadline=None,
                                    duration_minutes=db_row.get("estimated_duration_mins") or 30,
                                    labels=[],
                                    is_inbox=False,
                                )
                            )
                        except Exception:
                            pass

                session_tasks = session_tasks_by_day.get(candidate, [])
                windows = compute_free_windows(
                    events, candidate, context,
                    scheduled_tasks=db_blocked + session_tasks,
                )

                for window in windows:
                    if window.duration_minutes >= remaining:
                        slot_start = window.start
                        slot_end = slot_start + timedelta(minutes=remaining)
                        proposals.append((row, remaining, candidate, slot_start, slot_end))

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
                        session_tasks_by_day.setdefault(candidate, []).append(placeholder)
                        placed = True
                        break

                if placed:
                    break

            if not placed:
                proposals.append((row, remaining, None, None, None))

        for row, remaining, cand_date, slot_start, slot_end in proposals:
            if cand_date is None:
                print(f"\n  \u26a0\ufe0f  {row['task_name']} \u2192 needs manual scheduling")
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
                        orig_str = datetime.fromisoformat(orig_at).strftime("%Y-%m-%d %H:%M") if orig_at else "unknown"
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
        print(f"  Needs attention: {n_needs_attention} task(s) \u2014 schedule manually")
    print(f"{'=' * _W}\n")



def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Scheduling Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate data pipeline end-to-end (no LLM)",
    )
    parser.add_argument(
        "--plan-day",
        nargs="?",
        const="",
        default=None,
        metavar="DATE",
        help=(
            "Run full scheduling pipeline. "
            "Optional date: tomorrow | monday | 2026-04-07 (default: today)"
        ),
    )
    parser.add_argument(
        "--review",
        nargs="?",
        const="",
        default=None,
        metavar="DATE",
        help="Review today's scheduled tasks. Optional date: tomorrow | 2026-04-07 (default: today)",
    )
    parser.add_argument(
        "--add-task", type=str, metavar="TASK", help="Add a task to Todoist inbox"
    )
    args = parser.parse_args()

    context = _load_config()

    if args.check:
        _cmd_check(context)
    elif args.plan_day is not None:
        target_date = _resolve_target_date(args.plan_day)
        _cmd_plan_day(context, target_date)
    elif args.review is not None:
        target_date = _resolve_target_date(args.review)
        _cmd_review(context, target_date)
    elif args.add_task:
        print("[ERROR] --add-task not yet implemented")
        sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
