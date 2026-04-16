"""--plan-day command: filter → enrich → schedule → display → write-back."""

import json
import os
import sys
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.calendar_client import get_events
from src.db import setup_database
from src.llm import enrich_tasks, generate_schedule
from src.models import TodoistTask
from src.queries import (
    compute_deadline_pressure,
    get_all_active_budgets,
    get_task_history_for_sync,
    insert_schedule_log,
    insert_task_history,
)
from src.scheduler import compute_free_windows, pack_schedule
from src.schedule_pipeline import build_enriched_task_details
from src.sync_engine import run_sync
from src.todoist_client import TodoistClient, write_schedule_to_todoist

# Model names mirrored here for display in progress messages
ENRICH_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
SCHEDULE_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
_PRIORITY_API = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}
_WIDTH = 57

_TZ_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def _late_night_threshold_dt(base_date: date, context: dict, tz: ZoneInfo) -> datetime:
    """Return the late-night threshold as a timezone-aware datetime."""
    from src.scheduler import _parse_hm
    threshold_str = context.get("sleep", {}).get("late_night_threshold", "23:00")
    next_day = "next day" in threshold_str
    hm = threshold_str.replace("next day", "").strip()
    h, m = _parse_hm(hm)
    ref = base_date + timedelta(days=1) if next_day else base_date
    return datetime(ref.year, ref.month, ref.day, h, m, tzinfo=tz)


def _has_pre_meeting(block, events: list, context: dict) -> bool:
    """Return True if a Flamingo GCal event starts within 45 min after block.end_time."""
    flamingo_color = (
        context.get("calendar_rules", {})
        .get("flamingo", {})
        .get("color_id", "4")
    )
    for ev in events:
        if ev.is_all_day or ev.color_id != flamingo_color:
            continue
        gap_mins = int((ev.start - block.end_time).total_seconds() / 60)
        if 0 <= gap_mins <= 45:
            return True
    return False


def _display_schedule(
    blocks: list,
    pushed: list[dict],
    flagged: list[dict],
    reasoning_summary: str,
    task_map: dict,
    today: date,
    already_scheduled: list | None = None,
    tz: "ZoneInfo | None" = None,
) -> None:
    """Pretty-print the final schedule (ScheduledBlock objects) to the terminal."""
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
            if tz is not None:
                dt = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
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


def cmd_plan_day(context: dict, target_date: date) -> None:
    """
    --plan-day [DATE]: filter → enrich → confirm priorities → schedule → display → write-back.
    Read-only except for optional priority writes in Step C and confirmed write-back in Step F.
    """
    # Load productivity_science.json (fail fast if missing)
    prod_science_path = Path(__file__).parent.parent.parent / "productivity_science.json"
    if not prod_science_path.exists():
        print("[ERROR] productivity_science.json not found in project root")
        sys.exit(1)
    with open(prod_science_path) as f:
        prod_science = json.load(f)

    setup_database()

    # Auto-sync if re-running plan-day for a date that already has a schedule
    _existing_for_sync = get_task_history_for_sync(target_date.isoformat())
    if _existing_for_sync:
        print("[Sync] Existing schedule detected — checking for drift...")
        run_sync(context, target_date, silent=True)
        print()

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
        tz = ZoneInfo(tz_str)
        threshold_dt = _late_night_threshold_dt(day_before, context, tz)
        for ev in get_events(
            day_before, tz_str, extra_calendar_ids=context.get("calendar_ids", [])
        ):
            ev_end = ev.end if ev.end.tzinfo else ev.end.replace(tzinfo=tz)
            if not ev.is_all_day and ev_end >= threshold_dt:
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
    _tz_str_norm = _TZ_ALIASES.get(tz_str, tz_str)
    _tz = ZoneInfo(_tz_str_norm)

    already_scheduled = []  # has due_datetime on target_date — block time, show, skip LLM
    pinned_other_day = []   # has due_datetime on a different date — skip LLM, don't move
    schedulable = []        # has duration_minutes, no due_datetime — pass to LLM
    skipped = []            # no duration_minutes — skip entirely
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

    # ── Detect mid-day replanning ──────────────────────────────────────────────
    schedule_context = context
    if target_date == date.today() and windows:
        _tz_local = ZoneInfo(_tz_str_norm)
        _now = datetime.now(tz=_tz_local)
        _ft = context.get("sleep", {}).get("first_task_not_before", "10:30")
        _fth, _ftm = map(int, _ft.split(":"))
        _morning_cutoff = datetime(
            target_date.year, target_date.month, target_date.day, _fth, _ftm,
            tzinfo=_tz_local,
        )
        if _now > _morning_cutoff:
            hours_passed = (_now - _morning_cutoff).total_seconds() / 3600
            print(
                f"[Scheduler] Mid-day plan: starting from {windows[0].start.strftime('%H:%M')} "
                f"({hours_passed:.1f}h of morning already passed)"
            )
            _midday_rule = (
                f"NOTE: It is currently {_now.strftime('%H:%M')}. The morning peak window has "
                f"passed. Schedule from the afternoon secondary peak onwards. Do not reference "
                f"morning productivity windows — they are no longer available."
            )
            schedule_context = {
                **context,
                "rules": {
                    "hard": list(context.get("rules", {}).get("hard", [])) + [_midday_rule],
                    "soft": list(context.get("rules", {}).get("soft", [])),
                },
            }

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

    # ── Inject project budget synthetic tasks ─────────────────────────────────
    budgets = get_all_active_budgets()
    budget_task_objects = []
    if budgets:
        dw_windows = [w for w in windows if w.block_type in ("morning", "late night")]
        largest_dw_window = max((w.duration_minutes for w in dw_windows), default=0)
        largest_window = largest_dw_window or max(
            (w.duration_minutes for w in windows), default=0
        )
        _pressure_weight = {
            "critical": 3,
            "at_risk": 2,
            "comfortable": 1,
            "no_deadline": 1,
        }
        _priority_weight = {4: 4, 3: 3, 2: 2, 1: 1}

        scored = []
        for b in budgets:
            pressure = compute_deadline_pressure(
                b.get("deadline"), b["remaining_hours"]
            )
            pw = _priority_weight.get(b.get("priority", 3), 2)
            dw = _pressure_weight.get(pressure, 1)
            score = pw * dw

            session_min = b["session_min_minutes"]
            session_max = b["session_max_minutes"]
            _largest_morning = max(
                (w.duration_minutes for w in dw_windows if w.block_type == "morning"),
                default=0,
            )
            _largest_ln = max(
                (w.duration_minutes for w in dw_windows if w.block_type == "late night"),
                default=0,
            )
            if _largest_morning >= session_min:
                session_dur = min(session_max, _largest_morning)
            elif _largest_ln >= session_min:
                session_dur = min(session_max, _largest_ln)
            else:
                # No DW window meets session_min — schedule whatever fits rather
                # than handing pack_schedule a duration that will never fit and
                # cause the task to be pushed every day (see LEARNINGS.md).
                session_dur = min(session_max, largest_window) if largest_window > 0 else session_min

            scored.append((score, pressure, b, session_dur))

        scored.sort(key=lambda x: x[0], reverse=True)

        for score, pressure, b, session_dur in scored:
            t = TodoistTask(
                id=b["todoist_task_id"],
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
            budget_task_objects.append(t)
            if pressure in ("critical", "at_risk"):
                print(
                    f"  ⚠️  Budget [{b['project_name']}]  {b['remaining_hours']:.1f}h remaining  "
                    f"[{pressure.upper()}]"
                )

        if budget_task_objects:
            print(
                f"\n[Budget] {len(budget_task_objects)} project budget session(s) added to schedule"
            )
            schedulable = budget_task_objects + schedulable

    if not schedulable:
        print("\n[INFO] No unscheduled tasks to plan. Exiting.")
        return

    print(f"\n[Scheduler] {len(schedulable)} schedulable task(s) continuing to LLM…")

    task_map = {t.id: t for t in tasks}
    for t in budget_task_objects:
        task_map[t.id] = t

    # ── STEP B: Enrich schedulable tasks ──────────────────────────────────────
    print(f"[LLM] Step 1 — Enriching {len(schedulable)} tasks with {ENRICH_MODEL}…")
    enriched = enrich_tasks(schedulable, context, prod_science)
    print(f"[LLM] {len(enriched)} enrichment(s) returned")

    # ── STEP C: Priority confirmation for P4 / unset-priority tasks ───────────
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

        print()
        for num, enr, t in unset_items:
            final_label = overrides.get(num, enr.get("suggested_priority", "P4"))
            api_int = _PRIORITY_API.get(final_label, 1)
            try:
                todoist_client.update_task_priority(t.id, api_int)
                t.priority = api_int
                print(f'  ✓  "{t.content}"  →  {final_label}')
            except Exception as exc:
                print(f'  [WARN] Could not update priority for "{t.content}": {exc}')

    # ── STEP D: generate_schedule ──────────────────────────────────────────────
    enriched_with_details = build_enriched_task_details(schedulable, enriched_map, _PRIORITY_LABEL)

    print(f"\n[LLM] Step 2 — Generating schedule order with {SCHEDULE_MODEL}…")
    heuristics = prod_science.get("scheduling_heuristics_summary", {})
    schedule = generate_schedule(
        enriched_tasks=enriched_with_details,
        free_windows=windows,
        context=schedule_context,
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

    # Enforce P1 > P2 > P3 > P4 ordering regardless of LLM output.
    ordered_tasks.sort(
        key=lambda t: -(
            task_map[t["task_id"]].priority
            if t.get("task_id") in task_map
            else 1
        )
    )

    # ── STEP E: pack_schedule ─────────────────────────────────────────────────
    print("[Scheduler] Packing schedule into free windows…")
    blocks, auto_pushed = pack_schedule(
        ordered_tasks=ordered_tasks,
        free_windows=windows,
        context=context,
        target_date=target_date,
    )
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
        _tz,
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
    _ftb = context.get("sleep", {}).get("first_task_not_before", "10:30")
    for block in blocks:
        if block.split_part == 2:
            continue  # don't double-log split tasks
        original = task_map.get(block.task_id)
        enr = enriched_by_id.get(block.task_id, {})
        was_dw = int("deep-work" in (original.labels if original else []))
        pre_mtg = int(_has_pre_meeting(block, events, context))
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
            was_deep_work=was_dw,
            back_to_back=int(block.back_to_back),
            pre_meeting=pre_mtg,
            sync_source="agent",
            was_agent_scheduled=1,
            first_task_not_before=_ftb,
        )
