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

ONBOARD_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DRAFT_PATH = Path(__file__).parent.parent.parent / "context.json.draft"
DAYS_TO_SCAN = 14


def cmd_onboard(context: dict) -> None:
    timezone_str = context.get("user", {}).get("timezone", "America/Vancouver")
    extra_cal_ids = context.get("calendar_ids", [])

    # If a draft already exists and is at Stage 1, skip to Stage 2
    if DRAFT_PATH.exists():
        try:
            with open(DRAFT_PATH) as f:
                existing_draft = json.load(f)
            stage = existing_draft.get("_onboard_draft", {}).get("stage", 0)
            status = existing_draft.get("_onboard_draft", {}).get("status", "")
            if stage >= 1 and status == "pending_stage_2_qa":
                _run_stage_2(existing_draft, DRAFT_PATH)
                return
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupt draft — re-run Stage 1

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
                extra_calendar_ids=extra_cal_ids,
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
    draft = _build_draft_context(context, proposed, questions)
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


def _build_draft_context(existing_context: dict, proposed: dict, questions: list) -> dict:
    """
    Merge proposed values into a copy of the existing context.
    Only overwrites fields with non-null proposed values.
    Adds _onboard_draft metadata block for Stage 2 to read.
    """
    draft = copy.deepcopy(existing_context)

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
