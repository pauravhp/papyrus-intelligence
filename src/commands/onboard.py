"""
--onboard Stage 1: Calendar pattern detection + LLM draft config.

Scans 14 days of Google Calendar, detects patterns (wake time, color semantics,
recurring blocks, sleep signals), calls the LLM to propose a draft context.json,
and writes context.json.draft to the project root.

Does NOT overwrite the live context.json.
"""

import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from groq import Groq

from src.calendar_client import get_events
from src.llm import _groq_json_call
from src.onboard_patterns import build_pattern_summary
from src.prompts.onboard import build_onboard_prompt
from src.scheduler import compute_free_windows

ONBOARD_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DRAFT_PATH = Path(__file__).parent.parent.parent / "context.json.draft"
TEMPLATE_PATH = Path(__file__).parent.parent.parent / "context.template.json"
DAYS_TO_SCAN = 14


def cmd_onboard(context: dict) -> None:
    # Scan credentials only — sourced from live context.json, never written to draft
    timezone_str = context.get("user", {}).get("timezone", "America/Vancouver")
    extra_cal_ids = context.get("calendar_ids", [])

    # If a draft already exists, route to the appropriate stage
    if DRAFT_PATH.exists():
        try:
            with open(DRAFT_PATH) as f:
                existing_draft = json.load(f)
            stage = existing_draft.get("_onboard_draft", {}).get("stage", 0)
            status = existing_draft.get("_onboard_draft", {}).get("status", "")
            if stage >= 1 and status == "pending_stage_2_qa":
                _run_stage_2(existing_draft, DRAFT_PATH)
                return
            if stage >= 1 and status == "pending_stage_3_audit":
                _run_stage_3(existing_draft, DRAFT_PATH, timezone_str, extra_cal_ids)
                return
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupt draft — re-run Stage 1

    # Stage 1 — load template as draft base
    try:
        with open(TEMPLATE_PATH) as f:
            template = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] {TEMPLATE_PATH.name} not found. Cannot build draft.")
        return

    print("╔══════════════════════════════════════════════════════╗")
    print("║            --onboard  •  Stage 1 of 3               ║")
    print("║          Calendar Pattern Detection                  ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    # ── Fetch events ───────────────────────────────────────────────────────────
    today = date.today()
    start_date = today - timedelta(days=DAYS_TO_SCAN - 1)

    print(f"[Stage 1] Scanning {DAYS_TO_SCAN} days ({start_date} → {today})...")
    print()

    events_by_date: dict[date, list] = {}
    all_events: list = []

    for i in range(DAYS_TO_SCAN):
        target = start_date + timedelta(days=i)
        print(f"  {target} ...", end="\r", flush=True)
        try:
            day_events = get_events(
                target_date=target,
                timezone_str=timezone_str,
                calendar_ids=extra_cal_ids,
            )
            events_by_date[target] = day_events
            all_events.extend(day_events)
        except Exception as e:
            print(f"  [Warning] Could not fetch {target}: {e}          ")
            events_by_date[target] = []

    days_with = sum(1 for evts in events_by_date.values() if evts)
    print(f"  Fetched. {len(all_events)} events across {days_with}/{DAYS_TO_SCAN} days.          ")
    print()

    # ── Pattern detection ──────────────────────────────────────────────────────
    patterns = build_pattern_summary(events_by_date, all_events)
    _print_patterns(patterns)

    # ── LLM call ──────────────────────────────────────────────────────────────
    print("[LLM] Analyzing patterns and proposing configuration...")
    client = Groq()
    messages = build_onboard_prompt(patterns, context)

    try:
        raw = _groq_json_call(client, ONBOARD_MODEL, messages, "onboard_stage1")
    except RuntimeError as e:
        print(f"[ERROR] LLM call failed: {e}")
        return

    if not isinstance(raw, dict):
        print(f"[ERROR] Unexpected LLM response format: {type(raw)}")
        return

    proposed = raw.get("proposed_config", {}) or {}
    questions = raw.get("questions_for_stage_2", []) or []

    # ── Write draft ───────────────────────────────────────────────────────────
    draft = _build_draft_context(template, proposed, questions)
    with open(DRAFT_PATH, "w") as f:
        json.dump(draft, f, indent=2)

    print(f"  Done. Draft written to: {DRAFT_PATH.name}")
    print()

    # ── Preview questions ──────────────────────────────────────────────────────
    if questions:
        n = len(questions)
        print(f"── Stage 2 Preview: {n} question{'s' if n > 1 else ''} queued ───────────────────")
        for i, q in enumerate(questions[:5], 1):
            field = q.get("field", "?")
            conf = q.get("confidence", "?")
            question_text = q.get("question", "")
            snippet = question_text[:75]
            ellipsis = "..." if len(question_text) > 75 else ""
            print(f"  Q{i} [{conf}] {field}")
            print(f"     {snippet}{ellipsis}")
        print()

    print("── Next ────────────────────────────────────────────────")
    print(f"  Review draft:  cat {DRAFT_PATH.name}")
    print("  Continue:      python main.py --onboard  (Stage 2 — Q&A)")
    print()


def _print_patterns(patterns: dict) -> None:
    print("── Detected Patterns ───────────────────────────────────")

    wake = patterns.get("wake_times", {})
    print(f"  Weekdays : {wake.get('weekday_summary', 'n/a')}")
    print(f"  Weekends : {wake.get('weekend_summary', 'n/a')}")

    colors = patterns.get("color_semantics", {})
    for color_id, info in sorted(colors.items()):
        label = f"colorId {color_id}" if color_id != "none" else "(no color)"
        examples = ", ".join(info.get("top_names", [])[:2]) or "?"
        print(
            f"  {label:14s}  {info['count']:3d} events  "
            f"avg {info['avg_duration_min']:3d}min  "
            f"→ {info['likely_type']}  (e.g. {examples})"
        )

    recurring = patterns.get("recurring_blocks", [])
    if recurring:
        print(f"  Recurring ({len(recurring)}):")
        for r in recurring[:5]:
            print(
                f"    {r['name'][:38]:38s}  {r['day_of_week']:10s}  "
                f"~{r['time']}  ({r['occurrences_in_scan_window']}x)"
            )

    late_count = patterns.get("sleep_signals", {}).get("late_night_count", 0)
    if late_count:
        print(f"  Late nights: {late_count} event(s) ending after 10pm")

    print()


def _run_stage_2(draft: dict, draft_path: Path) -> None:
    """
    Interactive Q&A loop.

    Reads _onboard_draft.questions_for_stage_2, presents each question, captures
    user answers, applies them to the draft using dot-notation field paths, then
    writes the draft back with status = "pending_stage_3_audit".
    """
    draft = copy.deepcopy(draft)
    questions = draft.get("_onboard_draft", {}).get("questions_for_stage_2", [])

    print("╔══════════════════════════════════════════════════════╗")
    print("║            --onboard  •  Stage 2 of 3               ║")
    print("║              Interactive Q&A                         ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    if not questions:
        print("[Stage 2] No questions from Stage 1. Advancing to Stage 3.")
        draft["_onboard_draft"]["status"] = "pending_stage_3_audit"
        with open(draft_path, "w") as f:
            json.dump(draft, f, indent=2)
        print(f"  Draft updated: {draft_path.name}")
        return

    n = len(questions)
    print(f"  {n} question{'s' if n > 1 else ''} to answer. Press Enter to accept the inference.\n")

    answered = 0
    for i, q in enumerate(questions, 1):
        field = q.get("field", "?")
        question_text = q.get("question", "")
        inference = q.get("current_inference", "")
        confidence = q.get("confidence", "?")

        conf_tag = {"high": "[high]", "medium": "[med] ", "low": "[low] "}.get(confidence, f"[{confidence}]")

        print(f"── Q{i}/{n}  {conf_tag}  {field}")
        print(f"   {question_text}")
        if inference not in (None, "", "null"):
            prompt_str = f"   Your answer [{inference}]: "
        else:
            prompt_str = "   Your answer: "

        try:
            raw = input(prompt_str).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n[Stage 2] Interrupted. Draft NOT saved.")
            return

        # Empty → keep inference
        value = raw if raw else inference

        # Coerce numeric fields
        if value not in (None, "", "null"):
            if field.endswith("_minutes") or field.endswith("_min"):
                try:
                    value = int(value)
                except ValueError:
                    pass

        _set_nested(draft, field, value)
        answered += 1
        print()

    # Update metadata
    draft["_onboard_draft"]["status"] = "pending_stage_3_audit"
    draft["_onboard_draft"]["stage_2_completed_at"] = datetime.now().isoformat()
    draft["_onboard_draft"]["stage_2_answers_applied"] = answered

    with open(draft_path, "w") as f:
        json.dump(draft, f, indent=2)

    print(f"── {answered}/{n} answers applied ─────────────────────────────────")
    print(f"  Draft updated: {draft_path.name}")
    print()
    print("── Next ────────────────────────────────────────────────")
    print(f"  Review draft:  cat {draft_path.name}")
    print("  Continue:      python main.py --onboard  (Stage 3 — Audit & Promote)")
    print()


def _set_nested(d: dict, field_path: str, value) -> None:
    """
    Apply `value` to `d` at the dot-notation `field_path`.
    Creates intermediate dicts if missing. Skips if the leaf key doesn't
    exist in the original structure (avoids injecting unknown fields).
    """
    keys = field_path.split(".")
    node = d
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            # Don't create structure that doesn't exist in the draft
            return
        node = node[key]
    leaf = keys[-1]
    if leaf in node:
        node[leaf] = value
    # If the leaf doesn't exist, skip silently — don't add unknown fields


def _run_stage_3(draft: dict, draft_path: Path, scan_timezone: str, scan_cal_ids: list) -> None:
    """
    Free window audit.

    Strips _onboard_draft, runs compute_free_windows() against today using the
    draft config, displays the result for user confirmation, then promotes
    context.json.draft → context.json on approval.
    """
    CONTEXT_PATH = draft_path.parent / "context.json"
    BACKUP_PATH = draft_path.parent / "context.json.bak"

    print("╔══════════════════════════════════════════════════════╗")
    print("║            --onboard  •  Stage 3 of 3               ║")
    print("║              Free Window Audit                       ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    # Build working config: strip metadata, inject timezone if null
    working = copy.deepcopy(draft)
    working.pop("_onboard_draft", None)
    if working.get("user", {}).get("timezone") is None:
        working.setdefault("user", {})["timezone"] = scan_timezone
    # calendar_ids: use scan creds if draft has none
    if not working.get("calendar_ids"):
        working["calendar_ids"] = scan_cal_ids

    today = date.today()

    # ── Fetch today's events ───────────────────────────────────────────────────
    events = []
    try:
        print(f"[Stage 3] Fetching today's events ({today})...", end=" ", flush=True)
        events = get_events(
            target_date=today,
            timezone_str=scan_timezone,
            calendar_ids=scan_cal_ids,
        )
        print(f"{len(events)} event(s) found.")
    except Exception as e:
        print(f"\n  [Warning] Could not fetch events: {e}")
        print("  Proceeding with empty event list.")
    print()

    # ── Compute free windows ───────────────────────────────────────────────────
    try:
        windows = compute_free_windows(events, today, working)
    except Exception as e:
        print(f"[ERROR] compute_free_windows() failed: {e}")
        print("  Check that sleep times and calendar_rules in the draft are valid.")
        return

    # ── Display audit ──────────────────────────────────────────────────────────
    _display_audit(windows, events, working, today)

    # ── Confirm ────────────────────────────────────────────────────────────────
    try:
        answer = input('Does this look right? [y / describe an issue]: ').strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n\n[Stage 3] Interrupted. No changes made.")
        return

    if answer in ("", "y", "yes"):
        # ── Promote ───────────────────────────────────────────────────────────
        clean = copy.deepcopy(draft)
        clean.pop("_onboard_draft", None)

        if CONTEXT_PATH.exists():
            import shutil
            shutil.copy2(CONTEXT_PATH, BACKUP_PATH)
            print(f"  Backed up existing config → {BACKUP_PATH.name}")

        with open(CONTEXT_PATH, "w") as f:
            json.dump(clean, f, indent=2)

        draft_path.unlink()
        print(f"  Config promoted → {CONTEXT_PATH.name}")
        print(f"  Draft removed   → {draft_path.name}")
        print()
        print("  Onboarding complete. Run  python main.py --check  to validate.")
        print()
    else:
        # ── Guidance ──────────────────────────────────────────────────────────
        print()
        _print_fix_guidance(answer)
        print()
        print("  After editing, re-run:  python main.py --onboard")
        print()


def _display_audit(windows, events, working: dict, today) -> None:
    from zoneinfo import ZoneInfo
    from src.scheduler import _normalize_tz  # private but same codebase

    tz_str = _normalize_tz(working.get("user", {}).get("timezone", "America/Vancouver"))
    tz = ZoneInfo(tz_str)

    sleep = working.get("sleep", {})
    wake_str = sleep.get("default_wake_time") or "?"
    first_str = sleep.get("first_task_not_before") or "?"

    print(f"  Effective wake: {wake_str}  |  First task not before: {first_str}")
    print()

    # Free windows
    if windows:
        print("  Free windows:")
        for w in windows:
            s = w.start.astimezone(tz)
            e = w.end.astimezone(tz)
            h, m = divmod(w.duration_minutes, 60)
            dur = f"{h}h {m:02d}min" if h else f"{m}min"
            print(f"    {s.strftime('%H:%M')} → {e.strftime('%H:%M')}   ({dur:10s})   {w.block_type}")
    else:
        print("  No free windows found — check sleep config and daily blocks.")
    print()

    # Events consuming time
    cal_rules = working.get("calendar_rules", {})
    timed_events = [ev for ev in events if not ev.is_all_day]
    daily_blocks = working.get("daily_blocks", [])

    if timed_events or daily_blocks:
        print("  Events consuming time:")

        for ev in timed_events:
            buf_before = buf_after = 0
            rule_label = ""
            for rule_name, rule in cal_rules.items():
                if rule.get("color_id") == ev.color_id:
                    buf_before = rule.get("buffer_before_minutes", 0)
                    buf_after = rule.get("buffer_after_minutes", 0)
                    rule_label = f"  (colorId {ev.color_id} → {rule_name})"
                    break
            s = ev.start.astimezone(tz).strftime("%H:%M")
            e = ev.end.astimezone(tz).strftime("%H:%M")
            buf_str = f"+ {buf_before}min buffer each side" if buf_before or buf_after else "no buffer"
            print(f"    {ev.summary[:38]:38s}  {s}–{e}  {buf_str}{rule_label}")

        for db in daily_blocks:
            print(f"    {db['name'][:38]:38s}  {db['start']}–{db['end']}  (fixed daily block)")
    print()


_FIX_HINTS = [
    (["early", "too early", "first window", "morning start"],
     "sleep.first_task_not_before  or  sleep.morning_buffer_minutes"),
    (["wake", "wake time", "wakes"],
     "sleep.default_wake_time"),
    (["weekend", "saturday", "sunday"],
     "sleep.weekend_nothing_before"),
    (["buffer", "meeting", "call", "flamingo"],
     "calendar_rules.flamingo.buffer_before_minutes  /  buffer_after_minutes"),
    (["event", "banana"],
     "calendar_rules.banana.buffer_before_minutes  /  buffer_after_minutes"),
    (["color", "colour", "colorid"],
     "calendar_rules.flamingo.color_id  or  calendar_rules.banana.color_id"),
    (["lunch", "dinner", "block", "fixed"],
     "daily_blocks  (add/edit entries in context.json.draft)"),
    (["late", "night", "cutoff", "after"],
     "sleep.no_tasks_after"),
    (["sleep", "bedtime"],
     "sleep.default_sleep_time"),
]


def _print_fix_guidance(complaint: str) -> None:
    low = complaint.lower()
    matched = []
    for keywords, field_hint in _FIX_HINTS:
        if any(kw in low for kw in keywords):
            matched.append(field_hint)

    if matched:
        print("  Likely fields to edit in context.json.draft:")
        for hint in matched:
            print(f"    • {hint}")
    else:
        print("  Edit the relevant fields in context.json.draft, then re-run --onboard.")
        print("  Common fields: sleep.*, calendar_rules.*, daily_blocks")


def _build_draft_context(template: dict, proposed: dict, questions: list) -> dict:
    """
    Merge proposed values into a deepcopy of context.template.json.
    Only overwrites fields with non-null proposed values.
    Adds _onboard_draft metadata block for Stage 2 to read.
    """
    draft = copy.deepcopy(template)

    # Merge sleep fields
    for k, v in (proposed.get("sleep") or {}).items():
        if v is not None and k in draft.get("sleep", {}):
            draft["sleep"][k] = v

    # Merge calendar_rules (only update known rule names)
    for rule_name, rule in (proposed.get("calendar_rules") or {}).items():
        if rule_name in draft.get("calendar_rules", {}):
            for field, val in rule.items():
                if val is not None:
                    draft["calendar_rules"][rule_name][field] = val

    # Append newly detected daily blocks (skip if name already present)
    existing_names = {b["name"].lower() for b in draft.get("daily_blocks", [])}
    for block in (proposed.get("daily_blocks") or []):
        if block.get("name", "").lower() not in existing_names:
            draft.setdefault("daily_blocks", []).append(block)

    # Onboard metadata — Stage 2 reads this to pick up questions
    draft["_onboard_draft"] = {
        "stage": 1,
        "generated_at": datetime.now().isoformat(),
        "inferences": proposed.get("inferences", {}),
        "questions_for_stage_2": questions,
        "status": "pending_stage_2_qa",
    }

    return draft
