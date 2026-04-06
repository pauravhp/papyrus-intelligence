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
SCHEDULE_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


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
                    1 for b in blocks
                    if b.task_id == block.task_id and b.split_session
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
            print(textwrap.fill(f"  !   {name}: {issue}", width=_WIDTH, subsequent_indent="       "))

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
        events = get_events(target_date, tz_str)
        print(f"[GCal] {len(events)} event(s) found")
    except Exception as exc:
        print(f"[WARN] GCal fetch failed: {exc}")

    late_night_prior = False
    try:
        for ev in get_events(day_before, tz_str):
            if not ev.is_all_day and ev.end.hour >= 23:
                late_night_prior = True
                print(f"[GCal] Late night on {day_before} ({ev.summary} @ {ev.end.strftime('%H:%M')}) — buffer extended")
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

    # ── Scheduler ─────────────────────────────────────────────────────────────
    print("[Scheduler] Computing free windows…")
    windows = compute_free_windows(events, target_date, context, late_night_prior=late_night_prior)
    print(f"[Scheduler] {len(windows)} free window(s): " +
          ", ".join(f"{w.start.strftime('%H:%M')}–{w.end.strftime('%H:%M')}" for w in windows))

    if not tasks:
        print("[INFO] No tasks to schedule. Exiting.")
        return
    if not windows:
        print(f"[INFO] No free windows on {date_label}. Exiting.")
        return

    # ── STEP A: Filter — schedulable vs skipped ───────────────────────────────
    schedulable = [t for t in tasks if t.duration_minutes is not None]
    skipped = [t for t in tasks if t.duration_minutes is None]

    if skipped:
        print(f"\n⏭   Skipped (no duration label): {len(skipped)} task(s)")
        for t in skipped:
            print(f"    • {t.content}")
        print("    → Add @15min / @30min / @60min / @90min / @2h / @3h label in Todoist to schedule these")

    if not schedulable:
        print("\n[INFO] No schedulable tasks (all lack duration labels). Exiting.")
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
        print(f"\n⚠️   {len(unset_items)} task(s) have no priority set. Review suggestions:\n")
        for num, enr, t in unset_items:
            suggested = enr.get("suggested_priority", "P4")
            reason = enr.get("suggested_priority_reason", "")
            print(f"  [{num}] \"{t.content}\"  →  {suggested}")
            if reason:
                print(f"        └─ \"{reason}\"")

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
                t.priority = api_int  # update in-memory so display shows correct priority
                print(f"  ✓  \"{t.content}\"  →  {final_label}")
            except Exception as exc:
                print(f"  [WARN] Could not update priority for \"{t.content}\": {exc}")

    # ── STEP D: generate_schedule ──────────────────────────────────────────────
    # Build merged enrichment + task details for Step 2
    enriched_with_details = []
    for t in schedulable:
        base = enriched_map.get(t.id, {
            "task_id": t.id,
            "cognitive_load": "medium",
            "energy_requirement": "moderate",
            "suggested_block": "afternoon",
            "can_be_split": False,
            "scheduling_flags": ["never-schedule"] if "waiting" in t.labels else [],
        })
        enriched_with_details.append({
            **base,
            "content": t.content,
            "priority": _PRIORITY_LABEL.get(t.priority, "P4"),
            "duration_minutes": t.duration_minutes,
            "labels": t.labels,
            "deadline": t.deadline,
        })

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
    print(f"[LLM] {len(ordered_tasks)} task(s) ordered, {len(llm_pushed)} pushed by LLM")

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

    _display_schedule(blocks, llm_pushed, flagged, reasoning_summary, task_map, target_date)

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Scheduling Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true",
                        help="Validate data pipeline end-to-end (no LLM)")
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
    parser.add_argument("--review", action="store_true",
                        help="Review pushed/flagged tasks (Phase 2+)")
    parser.add_argument("--add-task", type=str, metavar="TASK",
                        help="Add a task to Todoist inbox")
    args = parser.parse_args()

    context = _load_config()

    if args.check:
        _cmd_check(context)
    elif args.plan_day is not None:
        target_date = _resolve_target_date(args.plan_day)
        _cmd_plan_day(context, target_date)
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
