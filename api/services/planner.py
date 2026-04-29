"""
Unified scheduling pipeline.

A single function — run_schedule_pipeline — used by all three scheduling
operations (Plan, Refine, Replan). Each operation is a thin wrapper that
shapes its inputs into the pipeline's signature.

PIPELINE SHAPE
  1. Pre-fetch (HTTP, no LLM): tasks + calendar events
  2. Extract constraints (LLM): turn user prose into structured blocks +
     cutoff_override, carrying forward state from previous turns
  3. Apply constraints (Python, deterministic): subtract blocks from events,
     override config.no_tasks_after if cutoff was extended, compute_free_windows
  4. Schedule (LLM): place tasks into already-constraint-aware free windows
  5. Validate (Python): reject window violations, GCal conflicts, and silent
     duration truncation
  6. Return

The split between extract-LLM and schedule-LLM eliminates the entire class of
"LLM declared a constraint but scheduled into it anyway" bugs we hit through
multiple rounds on 2026-04-25 — by the time the scheduler runs, the windows
are already constraint-aware, so it cannot violate them by construction.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.calendar_client import create_event, get_events
from src.models import CalendarEvent, TodoistTask
from src.scheduler import compute_free_windows
from src.todoist_client import TodoistClient
from api.services.defaults import with_meal_defaults
from api.services.extractor import Block, ExtractionResult, extract_constraints
from api.services.rhythm_service import get_active_rhythms
from api.services.schedule_service import schedule_day

logger = logging.getLogger(__name__)

# Truncation tolerance — accept a duration up to this fraction below the
# original. Below this, we treat it as silent shortening and reject. Tuned to
# allow tiny rounding (LLM emits 89 vs original 90) without rejecting it.
_TRUNCATION_TOLERANCE = 0.95

# Window in which a repeat /api/plan/confirm or /api/replan/confirm POST is
# treated as a UI double-click and replayed idempotently instead of writing
# duplicate GCal events. Sized to absorb network retries without blocking a
# legitimate "confirm now, replan later" flow (which takes minutes of UI work).
IDEMPOTENCY_WINDOW_SECONDS = 30

# Floor on schedulable time below which "Plan today" returns the empty-with-
# suggestion shape rather than calling schedule_day. < 30 minutes can't fit a
# meaningful task block (the smallest @duration label users typically use is
# @15min and even that needs setup/transition time at this hour).
_LATE_NIGHT_MIN_MINUTES = 30


class AlreadyConfirmedError(Exception):
    """Raised when plan/confirm is called for a date that already has a
    confirmed schedule_log row outside the idempotency window. The route
    layer translates this to HTTP 409."""


def _parse_confirmed_at(value) -> datetime | None:
    """Best-effort parse of schedule_log.confirmed_at (ISO text). Returns
    a tz-aware datetime, or None if unparseable."""
    if not value or not isinstance(value, str):
        return None
    try:
        # Accept trailing 'Z' as UTC
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


def _is_within_idempotency_window(confirmed_at_iso) -> bool:
    dt = _parse_confirmed_at(confirmed_at_iso)
    if dt is None:
        return False
    now = datetime.now(dt.tzinfo)
    return 0 <= (now - dt).total_seconds() < IDEMPOTENCY_WINDOW_SECONDS


# ── Helpers ────────────────────────────────────────────────────────────────────


def _ensure_meal_blocks(config: dict) -> dict:
    return with_meal_defaults(config)


def _resolve_calendar_ids(config: dict) -> list[str]:
    return (
        config.get("source_calendar_ids")
        or config.get("calendar_ids")
        or ["primary"]
    )


def _tz_offset_str(tz_str: str, target_date: date) -> str:
    """Return the user's UTC offset on target_date, e.g. '-07:00'."""
    tz = ZoneInfo(tz_str)
    sample = datetime.combine(target_date, time(12, 0), tz)
    raw = sample.strftime("%z")  # "-0700"
    if len(raw) == 5:
        return f"{raw[:3]}:{raw[3:]}"
    return raw or "+00:00"


def _block_to_calendar_event(block: Block) -> CalendarEvent | None:
    """Convert an extractor Block into a CalendarEvent for window math."""
    try:
        start_dt = datetime.fromisoformat(block.start_iso)
        end_dt = datetime.fromisoformat(block.end_iso)
    except ValueError:
        return None
    if end_dt <= start_dt:
        return None
    sh, sm = start_dt.hour, start_dt.minute
    eh, em = end_dt.hour, end_dt.minute
    return CalendarEvent(
        id=f"user_block_{sh:02d}{sm:02d}_{eh:02d}{em:02d}",
        summary=block.source or "User-stated block",
        start=start_dt,
        end=end_dt,
        color_id=None,
        is_all_day=False,
    )


def _apply_cutoff_override(config: dict, cutoff_iso: str | None, target_date: date) -> dict:
    """
    Apply an extractor-supplied cutoff_override_iso to the config used for
    THIS request only. Doesn't touch the user's saved config.

    compute_free_windows reads sleep.no_tasks_after as either "HH:MM" or
    "HH:MM next day"; we honor both shapes. A cutoff on target_date+1 becomes
    "HH:MM next day", same-day stays as "HH:MM".
    """
    if not cutoff_iso:
        return config
    try:
        cutoff_dt = datetime.fromisoformat(cutoff_iso)
    except ValueError:
        logger.warning("[planner] cutoff_override_iso unparseable: %r", cutoff_iso)
        return config

    if cutoff_dt.date() > target_date:
        override_str = f"{cutoff_dt.strftime('%H:%M')} next day"
    else:
        override_str = cutoff_dt.strftime("%H:%M")

    new_sleep = {**config.get("sleep", {}), "no_tasks_after": override_str}
    return {**config, "sleep": new_sleep}


def _load_self_written_event_ids(supabase, user_id: str, target_date: date) -> set[str]:
    """Return GCal event IDs Papyrus wrote during the most recent confirmed
    schedule for (user, target_date), or an empty set if no row exists or the
    column is unparseable.

    Used to keep the planner from treating its own writes as calendar
    conflicts when re-planning the same day (e.g. /api/refine after
    /api/plan/confirm). Without this, the LLM sees the events it just placed
    as immovable obstacles and pushes the rescheduled tasks.
    """
    try:
        result = (
            supabase.from_("schedule_log")
            .select("gcal_event_ids")
            .eq("user_id", user_id)
            .eq("schedule_date", target_date.isoformat())
            .eq("confirmed", 1)
            .order("confirmed_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.warning("[planner] schedule_log lookup failed: %s", exc)
        return set()

    rows = result.data or []
    if not rows:
        return set()
    raw = rows[0].get("gcal_event_ids")
    if not raw:
        return set()
    try:
        ids = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(ids, list):
        return set()
    return {x for x in ids if isinstance(x, str)}


def _compute_rhythm_sessions_done_this_week(supabase, user_id: str, target_date: date) -> dict[str, int]:
    week_start = target_date - timedelta(days=target_date.weekday())
    try:
        rows = (
            supabase.from_("schedule_log")
            .select("schedule_date, proposed_json, confirmed")
            .eq("user_id", user_id)
            .eq("confirmed", 1)
            .gte("schedule_date", week_start.isoformat())
            .lte("schedule_date", target_date.isoformat())
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("schedule_log query failed: %s", exc)
        return {}

    counts: dict[str, int] = {}
    for row in rows:
        try:
            proposed = json.loads(row.get("proposed_json") or "{}")
            for item in proposed.get("scheduled") or []:
                tid = item.get("task_id", "")
                if tid.startswith("proj_"):
                    counts[tid] = counts.get(tid, 0) + 1
        except Exception:
            continue
    return counts


def _rhythm_priority(sessions_remaining: int, target_date: date) -> int:
    days_remaining = 7 - target_date.weekday()
    urgency = sessions_remaining / max(1, days_remaining)
    if urgency >= 0.8:
        return 4
    if urgency >= 0.4:
        return 3
    return 2


# Map Python's weekday() (0=Mon..6=Sun) to the lowercase ISO names stored in
# rhythms.days_of_week. Single source of truth so any future filter agrees.
_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _rhythm_applies_today(rhythm: dict, target_date: date) -> bool:
    """True if the rhythm should be considered for placement on target_date.

    A rhythm with `days_of_week` NULL or empty applies every day (legacy
    backward-compat: existing rhythms predate the column). A rhythm with a
    populated list applies only on those weekdays.
    """
    days = rhythm.get("days_of_week")
    if not days:
        return True
    today_name = _WEEKDAY_NAMES[target_date.weekday()]
    return today_name in days


def _inject_synthetic_rhythms(
    supabase,
    user_id: str,
    target_date: date,
    base_tasks: list[TodoistTask],
    task_names: dict[str, str],
) -> list[TodoistTask]:
    active = get_active_rhythms(user_id, supabase)
    sessions_done = _compute_rhythm_sessions_done_this_week(supabase, user_id, target_date)

    synthetic: list[TodoistTask] = []
    for rhythm in active:
        if not _rhythm_applies_today(rhythm, target_date):
            continue
        per_week = int(rhythm["sessions_per_week"])
        done = sessions_done.get(f"proj_{rhythm['id']}", 0)
        remaining = max(0, per_week - done)
        if remaining == 0:
            continue
        # The hint (rhythm.description) is internal LLM-coaching context — NOT
        # user-facing copy. Keep `content` as the bare rhythm_name (this becomes
        # the displayed task_name in responses + the GCal event title) and
        # plumb the hint through `rhythm_hint` so the prompt builder can render
        # it inline without leaking to the frontend.
        rhythm_name = rhythm["rhythm_name"]
        synthetic.append(TodoistTask(
            id=f"proj_{rhythm['id']}",
            content=rhythm_name,
            project_id="rhythm",
            priority=_rhythm_priority(remaining, target_date),
            due_datetime=None,
            deadline=None,
            duration_minutes=int(rhythm["session_min_minutes"]),
            labels=[],
            is_inbox=False,
            is_rhythm=True,
            session_max_minutes=int(rhythm["session_max_minutes"]),
            sessions_per_week=per_week,
            rhythm_hint=rhythm.get("description") or None,
        ))
        task_names[f"proj_{rhythm['id']}"] = rhythm_name

    return synthetic + base_tasks


# Validator's truncation-rejection reason is anchored on this prefix. The
# auto-retry logic detects truncations in the validated proposal by scanning
# pushed[] for this exact prefix — keep _validate_proposed and this in sync.
_TRUNCATION_REASON_PREFIX = "Couldn't fit the full duration"


def _detect_truncations(validated: dict) -> list[dict]:
    """Return pushed entries that are validator-flagged truncations. Empty
    list means the proposal has no shortened tasks (no retry needed)."""
    return [
        p for p in validated.get("pushed", [])
        if isinstance(p.get("reason"), str)
        and p["reason"].startswith(_TRUNCATION_REASON_PREFIX)
    ]


def _build_truncation_retry_feedback(truncations: list[dict]) -> str:
    """Build a one-shot instruction for the LLM listing the exact tasks it
    truncated. Surfaced as additional context_note on the retry call."""
    lines = [
        "YOUR PREVIOUS ATTEMPT TRUNCATED THESE TASKS — PUSH THEM INSTEAD OF SHORTENING:",
    ]
    for p in truncations:
        name = p.get("task_name") or p.get("task_id", "")
        lines.append(f"  - {name}: {p['reason']}")
    lines.append(
        "Re-output the full schedule. For each task above, either place it at its FULL "
        "stated duration in any free window OR push it with reason \"didn't fit\". "
        "Do NOT shorten them again — truncated placements are rejected by the validator "
        "and the task disappears from the schedule entirely."
    )
    return "\n".join(lines)


def _build_original_durations(tasks: list[TodoistTask]) -> dict[str, dict]:
    """
    Map task_id → {min_duration, max_duration, name} for truncation enforcement.
    Rhythms accept a range; one-off tasks have a fixed duration.
    """
    out: dict[str, dict] = {}
    for t in tasks:
        if t.duration_minutes is None:
            continue
        if t.is_rhythm and t.session_max_minutes:
            out[t.id] = {
                "min": int(t.duration_minutes),
                "max": int(t.session_max_minutes),
                "name": t.content,
                "is_rhythm": True,
            }
        else:
            out[t.id] = {
                "min": int(t.duration_minutes),
                "max": int(t.duration_minutes),
                "name": t.content,
                "is_rhythm": False,
            }
    return out


def _validate_proposed(
    proposed: dict,
    real_events: list[CalendarEvent],
    user_blocks: list[CalendarEvent],
    free_windows,
    original_durations: dict[str, dict],
    task_names: dict[str, str],
) -> dict:
    """
    Three-way Python validator on the LLM's scheduled list:
      - GCal conflict: item overlaps a real calendar event → reject
      - User block conflict: item overlaps an extracted user-stated block → reject
      - Truncation: item's duration is below the original task's minimum → reject

    For rhythm tasks split into pt 1 / pt 2 (same task_id, different start_time),
    we sum durations across all parts before applying the truncation check, so
    a legitimate split isn't mistaken for shrinkage.
    """
    real_timed = [e for e in (real_events or []) if not e.is_all_day]
    block_timed = [e for e in (user_blocks or []) if not e.is_all_day]

    valid: list[dict] = []
    rejected: list[dict] = []

    # Group items by task_id so split parts (pt 1 / pt 2) can be summed for
    # truncation comparison.
    items_by_id: dict[str, list[dict]] = {}
    for item in proposed.get("scheduled", []):
        tid = item.get("task_id", "")
        items_by_id.setdefault(tid, []).append(item)

    for tid, items in items_by_id.items():
        # Per-item conflict checks
        per_item_kept: list[dict] = []
        for item in items:
            try:
                item_start = datetime.fromisoformat(item["start_time"])
                item_end = datetime.fromisoformat(item["end_time"])
            except (KeyError, ValueError) as exc:
                logger.warning("scheduled item parse error %s — accepting as-is: %s", exc, item)
                per_item_kept.append(item)
                continue

            gcal_conflict = any(
                item_start < e.end and item_end > e.start
                for e in real_timed
            )
            block_conflict = next(
                (e for e in block_timed if item_start < e.end and item_end > e.start),
                None,
            )

            if gcal_conflict:
                rejected.append({
                    "task_id": tid,
                    "task_name": item.get("task_name") or task_names.get(tid, tid),
                    "reason": "Conflicts with an existing calendar event",
                })
                continue
            if block_conflict:
                phrase = block_conflict.summary if block_conflict.summary != "User-stated block" else "this time"
                rejected.append({
                    "task_id": tid,
                    "task_name": item.get("task_name") or task_names.get(tid, tid),
                    "reason": f"You blocked {phrase}",
                })
                continue
            per_item_kept.append(item)

        # Truncation check on the kept parts (sum durations across split pieces)
        original = original_durations.get(tid)
        if original and per_item_kept:
            total_dur = sum(int(p.get("duration_minutes", 0) or 0) for p in per_item_kept)
            min_required = int(original["min"] * _TRUNCATION_TOLERANCE)
            if total_dur < min_required:
                # Truncated. Reject ALL parts and surface as one push.
                rejected.append({
                    "task_id": tid,
                    "task_name": original["name"],
                    "reason": f"Couldn't fit the full duration ({original['min']}m needed, {total_dur}m placed)",
                })
                continue

        valid.extend(per_item_kept)

    out = dict(proposed)
    out["scheduled"] = valid
    out["pushed"] = list(proposed.get("pushed", [])) + rejected
    return out


def _restore_full_names(proposed: dict, task_names: dict[str, str]) -> dict:
    for item in proposed.get("scheduled", []):
        tid = item.get("task_id")
        if tid and tid in task_names:
            item["task_name"] = task_names[tid]
    for item in proposed.get("pushed", []):
        if not item.get("task_name"):
            tid = item.get("task_id", "")
            item["task_name"] = task_names.get(tid, tid)
    return proposed


def _format_previous_proposal(previous: dict) -> str:
    """
    Render the prior turn's scheduled list. Category is included so the
    scheduler LLM can honor CATEGORY STABILITY — without it the LLM has no
    way to know what each task was previously classified as and reclassifies
    randomly between turns.
    """
    lines: list[str] = []
    for item in previous.get("scheduled", []):
        try:
            start = datetime.fromisoformat(item["start_time"]).strftime("%H:%M")
            end = datetime.fromisoformat(item["end_time"]).strftime("%H:%M")
            name = item.get("task_name", "")
            dur = item.get("duration_minutes", "")
            tid = item.get("task_id", "")
            cat = item.get("category") or "untagged"
            lines.append(f"- [{tid}] {name} {start}–{end} ({dur}m) category={cat}")
        except Exception:
            continue
    return "\n".join(lines) if lines else "(empty)"


def _previous_blocks_from_dict(previous: dict | None) -> list[Block]:
    """Read carry-forward blocks from a previous response. Tolerates either the
    new shape (list of {start_iso,end_iso,source}) or absent."""
    if not previous:
        return []
    raw = previous.get("blocks") or []
    out: list[Block] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        b = Block.from_dict(d)
        if b is not None:
            out.append(b)
    return out


# ── Core pipeline ──────────────────────────────────────────────────────────────


def run_schedule_pipeline(
    *,
    user_ctx: dict,
    target_date: date,
    prose: str = "",
    candidate_tasks: list[TodoistTask] | None = None,
    inject_rhythms: bool = True,
    previous_proposal: dict | None = None,
    is_refinement: bool = False,
) -> dict:
    """
    The unified scheduling pipeline. Plan, Refine, and Replan all flow through
    this function with different input shaping.

    Args:
      user_ctx: as built by the route handlers (config, todoist key, gcal service, supabase).
      target_date: which date to plan.
      prose: the user's natural-language note for THIS turn. Empty string is fine.
      candidate_tasks: explicit task list to schedule. When None, fetch from Todoist
        with the standard "today | overdue" / "tomorrow" filter. Replan supplies
        its own list (kept-from-triage + backlog).
      inject_rhythms: whether to add synthetic rhythm tasks. Replan disables this
        because its candidate list already includes whatever rhythms apply via
        the morning's confirmed schedule.
      previous_proposal: the prior turn's response; carries blocks + cutoff +
        scheduled-baseline. Required for Refine; optional otherwise.
      is_refinement: marks this call as a refinement (changes the scheduler
        prompt's framing — diff from baseline rather than fresh plan).

    Returns:
      {
        scheduled, pushed, reasoning_summary,
        blocks, cutoff_override,
        free_windows_used,
      }
    """
    # ── 0. Setup ──────────────────────────────────────────────────────────────
    config = _ensure_meal_blocks(user_ctx["config"])
    # Default matches src/scheduler.py — must stay in sync, otherwise the extractor
    # and compute_free_windows disagree on the user's local time and we end up
    # blocking the wrong hour-of-day. Caught on 2026-04-25: extractor saw UTC,
    # compute_free_windows saw Vancouver, blocks landed at the wrong wall-clock time.
    tz_str = config.get("user", {}).get("timezone") or "America/Vancouver"
    cal_ids = _resolve_calendar_ids(config)
    target_date_str = target_date.isoformat()
    tz_offset = _tz_offset_str(tz_str, target_date)
    print(
        f"[pipeline] target_date={target_date_str} tz_str={tz_str} "
        f"tz_offset={tz_offset} (config.user.timezone={config.get('user', {}).get('timezone')!r})"
    )

    # Carry-forward state from prior turn (if any)
    prev_blocks = _previous_blocks_from_dict(previous_proposal)
    prev_cutoff = (previous_proposal or {}).get("cutoff_override")

    # ── 1. Extract constraints (LLM) ──────────────────────────────────────────
    extracted: ExtractionResult = extract_constraints(
        prose=prose,
        target_date_str=target_date_str,
        tz_offset=tz_offset,
        previous_blocks=prev_blocks,
        previous_cutoff_iso=prev_cutoff,
        anthropic_api_key=user_ctx.get("anthropic_api_key"),
    )
    logger.info(
        "[pipeline] extracted blocks=%d cutoff=%s",
        len(extracted.blocks), extracted.cutoff_override_iso,
    )

    user_blocks_events: list[CalendarEvent] = []
    for b in extracted.blocks:
        ev = _block_to_calendar_event(b)
        if ev is not None:
            user_blocks_events.append(ev)
        else:
            print(f"[pipeline] WARNING: extracted block dropped during conversion: {b}")

    print(
        f"[pipeline] user_blocks_events going to compute_free_windows: "
        f"{[(e.start.isoformat(), e.end.isoformat()) for e in user_blocks_events]}"
    )

    # ── 2. Apply constraints to config ────────────────────────────────────────
    config_for_request = _apply_cutoff_override(config, extracted.cutoff_override_iso, target_date)
    if extracted.cutoff_override_iso:
        print(
            f"[pipeline] cutoff_override applied: "
            f"no_tasks_after={config_for_request.get('sleep', {}).get('no_tasks_after')}"
        )

    # ── 3. Pre-fetch tasks + GCal ─────────────────────────────────────────────
    todoist = TodoistClient(user_ctx["todoist_api_key"])
    today = date.today()

    if candidate_tasks is None:
        task_filter = "tomorrow" if target_date > today else "today | overdue"
        all_tasks = todoist.get_tasks(task_filter)
    else:
        all_tasks = candidate_tasks

    task_names: dict[str, str] = {t.id: t.content for t in all_tasks}
    tasks = [t for t in all_tasks if t.duration_minutes is not None]
    if inject_rhythms:
        tasks = _inject_synthetic_rhythms(
            user_ctx["supabase"], user_ctx["user_id"], target_date, tasks, task_names,
        )

    real_events = (
        get_events(
            target_date=target_date,
            timezone_str=tz_str,
            calendar_ids=cal_ids,
            service=user_ctx.get("gcal_service"),
        )
        if user_ctx.get("gcal_service")
        else []
    )

    # Drop events Papyrus itself wrote during a prior confirm for this date.
    # Otherwise the LLM treats its own writes as conflicts on the next
    # /api/refine and pushes the rescheduled tasks.
    self_written_ids = _load_self_written_event_ids(
        user_ctx.get("supabase"), user_ctx.get("user_id"), target_date,
    )
    if self_written_ids:
        before = len(real_events)
        real_events = [e for e in real_events if e.id not in self_written_ids]
        logger.info(
            "[pipeline] excluded %d self-written events from %d total",
            before - len(real_events), before,
        )

    logger.info(
        "[pipeline] tz=%s real_events=%d user_blocks=%d cutoff_override=%s",
        tz_str, len(real_events), len(user_blocks_events), extracted.cutoff_override_iso,
    )

    # ── 4. Compute free windows (already constraint-aware) ───────────────────
    events_for_windows = real_events + user_blocks_events
    scheduled_tasks = todoist.get_todays_scheduled_tasks(target_date)
    free_windows = compute_free_windows(
        events_for_windows, target_date, config_for_request,
        scheduled_tasks=scheduled_tasks,
    )
    print(
        f"[pipeline] free_windows after constraints: "
        f"{[(w.start.strftime('%H:%M'), w.end.strftime('%H:%M'), w.duration_minutes) for w in free_windows]}"
    )
    already_ids = {t.id for t in scheduled_tasks}
    tasks = [t for t in tasks if t.id not in already_ids]

    # Late-night short-circuit. Plan today is meaningless once today's effective
    # cutoff has passed (or only a sliver of time is left). The frontend pivots
    # on auto_shift_to_tomorrow_suggested=True to render a "Plan tomorrow" CTA
    # instead of an empty schedule grid. We short-circuit BEFORE the schedule_day
    # LLM call to save tokens and keep the response shape unambiguous (no
    # rejected items leaking into pushed[]).
    total_free_minutes = sum(w.duration_minutes for w in free_windows)
    if target_date == date.today() and total_free_minutes < _LATE_NIGHT_MIN_MINUTES:
        tz = ZoneInfo(tz_str)
        now_local = datetime.now(tz).strftime("%I:%M %p").lstrip("0")
        return {
            "scheduled": [],
            "pushed": [],
            "reasoning_summary": (
                f"It's already {now_local} — there's no meaningful time left "
                f"to plan today. Want to plan tomorrow instead?"
            ),
            "blocks": [b.to_dict() for b in extracted.blocks],
            "cutoff_override": extracted.cutoff_override_iso,
            "free_windows_used": [],
            "auto_shift_to_tomorrow_suggested": True,
        }

    original_durations = _build_original_durations(tasks)

    # ── 5. Schedule (LLM) ─────────────────────────────────────────────────────
    scheduler_context = _build_scheduler_context(
        prose=prose,
        previous_proposal=previous_proposal,
        is_refinement=is_refinement,
    )

    proposed = schedule_day(
        tasks=tasks,
        free_windows=free_windows,
        config=config_for_request,
        context_note=scheduler_context,
        anthropic_api_key=user_ctx.get("anthropic_api_key"),
        target_date=target_date_str,
        events=events_for_windows,
    )

    # ── 6. Validate ───────────────────────────────────────────────────────────
    proposed = _validate_proposed(
        proposed, real_events, user_blocks_events, free_windows,
        original_durations, task_names,
    )

    # ── 6b. Auto-retry on truncation (single retry, no loop) ──────────────────
    # The schedule_day prompt tells the LLM "DURATIONS ARE FIXED; never shorten."
    # Despite that, Haiku occasionally squeezes a task into a too-small window
    # by truncating its duration. The validator catches it and rejects, but the
    # task is then invisible to the user (a feature loss with no upside).
    #
    # Retry exactly once with explicit feedback naming the truncated tasks.
    # If the retry's validator output has zero truncations, use it. Otherwise
    # keep the first attempt's result (the rejections are at least surfaced
    # in pushed[], and a second LLM call with the same outcome is wasted spend).
    truncations = _detect_truncations(proposed)
    if truncations:
        logger.warning(
            "[pipeline] schedule_day truncated %d task(s); retrying once with feedback",
            len(truncations),
        )
        feedback = _build_truncation_retry_feedback(
            _restore_full_names({"pushed": list(truncations)}, task_names)["pushed"]
        )
        retry_context = (
            f"{scheduler_context}\n\n{feedback}" if scheduler_context else feedback
        )
        retry_proposed = schedule_day(
            tasks=tasks,
            free_windows=free_windows,
            config=config_for_request,
            context_note=retry_context,
            anthropic_api_key=user_ctx.get("anthropic_api_key"),
            target_date=target_date_str,
            events=events_for_windows,
        )
        retry_validated = _validate_proposed(
            retry_proposed, real_events, user_blocks_events, free_windows,
            original_durations, task_names,
        )
        if not _detect_truncations(retry_validated):
            proposed = retry_validated
        else:
            logger.warning("[pipeline] retry still truncated — keeping first attempt's result")

    proposed = _restore_full_names(proposed, task_names)

    # ── 7. Persist constraints + windows for next turn ────────────────────────
    proposed["blocks"] = [b.to_dict() for b in extracted.blocks]
    proposed["cutoff_override"] = extracted.cutoff_override_iso
    proposed["free_windows_used"] = [
        {
            "start": w.start.strftime("%H:%M"),
            "end": w.end.strftime("%H:%M"),
            "duration_minutes": w.duration_minutes,
        }
        for w in free_windows
    ]
    return proposed


def _build_scheduler_context(
    *,
    prose: str,
    previous_proposal: dict | None,
    is_refinement: bool,
) -> str:
    """
    Build the context_note passed to the scheduler LLM.

    The scheduler does NOT need to extract constraints (that already happened);
    it only needs to know the user's preferences/intent for placement and, on
    refinement turns, the previous baseline to diff from.
    """
    parts: list[str] = []
    if prose:
        parts.append(f"USER NOTE: {prose}")
    if is_refinement and previous_proposal is not None:
        baseline = _format_previous_proposal(previous_proposal)
        parts.append(f"PREVIOUS PROPOSAL (your baseline — diff from this; only change what the user asked):\n{baseline}")
    return "\n\n".join(parts)


# ── Public wrappers ───────────────────────────────────────────────────────────


def plan(
    user_ctx: dict,
    target_date: date,
    context_note: str = "",
) -> dict:
    """Initial plan for target_date."""
    return run_schedule_pipeline(
        user_ctx=user_ctx,
        target_date=target_date,
        prose=context_note or "",
    )


def refine(
    user_ctx: dict,
    target_date: date,
    previous_proposal: dict,
    refinement_message: str,
    original_context_note: str = "",
) -> dict:
    """Refine an existing proposal."""
    prose_parts = [p for p in (original_context_note or "", refinement_message or "") if p]
    prose = "\n\n".join(prose_parts)
    return run_schedule_pipeline(
        user_ctx=user_ctx,
        target_date=target_date,
        prose=prose,
        previous_proposal=previous_proposal,
        is_refinement=True,
    )


def replan(
    user_ctx: dict,
    target_date: date,
    candidate_tasks: list[TodoistTask],
    prose: str,
    previous_proposal: dict | None = None,
) -> dict:
    """
    Mid-day replan with an explicit candidate task list (kept-from-triage +
    backlog). compute_free_windows handles the mid-day "start from now"
    detection automatically when target_date == date.today().
    """
    return run_schedule_pipeline(
        user_ctx=user_ctx,
        target_date=target_date,
        prose=prose,
        candidate_tasks=candidate_tasks,
        inject_rhythms=False,  # replan inherits the morning's rhythm decisions
        previous_proposal=previous_proposal,
        is_refinement=previous_proposal is not None,
    )


def confirm(
    user_ctx: dict,
    schedule: dict,
    target_date: date,
    target_calendar_id: str | None = None,
) -> dict:
    """
    Write the proposed schedule: GCal events + Todoist due_datetimes +
    schedule_log row with confirmed=1. Zero LLM calls.

    Double-confirm guard: if a confirmed schedule_log row already exists for
    (user, target_date), either replay it idempotently (recent click) or
    raise AlreadyConfirmedError (older row — caller should use replan).
    """
    supabase = user_ctx["supabase"]

    existing = (
        supabase.from_("schedule_log")
        .select("id, confirmed_at, gcal_event_ids, replan_trigger")
        .eq("user_id", user_ctx["user_id"])
        .eq("schedule_date", target_date.isoformat())
        .eq("confirmed", 1)
        .order("confirmed_at", desc=True)
        .limit(1)
        .execute()
    )
    existing_row = (existing.data or [None])[0]
    if existing_row:
        if _is_within_idempotency_window(existing_row.get("confirmed_at")):
            try:
                gcal_ids = json.loads(existing_row.get("gcal_event_ids") or "[]")
            except (json.JSONDecodeError, TypeError):
                gcal_ids = []
            return {
                "confirmed": True,
                "gcal_events_created": len(gcal_ids),
                "todoist_updated": 0,
                "schedule_log_id": existing_row.get("id"),
            }
        raise AlreadyConfirmedError(
            "Today is already confirmed. Use Replan to update the rest of the day."
        )

    config = user_ctx["config"]
    tz_str = config.get("user", {}).get("timezone", "UTC")
    write_cal_id = (target_calendar_id if target_calendar_id else None) or config.get("write_calendar_id", "primary")
    todoist = TodoistClient(user_ctx["todoist_api_key"])

    gcal_event_ids: list[str] = []
    todoist_updated = 0

    for item in schedule.get("scheduled", []):
        try:
            start_dt = datetime.fromisoformat(item["start_time"])
            end_dt = datetime.fromisoformat(item["end_time"])
            gcal_id = create_event(
                user_ctx["gcal_service"],
                title=item["task_name"],
                start_dt=start_dt,
                end_dt=end_dt,
                timezone_str=tz_str,
                calendar_id=write_cal_id,
            )
            gcal_event_ids.append(gcal_id)
        except Exception as exc:
            logger.warning("[planner.confirm] GCal create failed for %s: %s", item.get("task_name"), exc)

        if not item.get("task_id", "").startswith("proj_"):
            try:
                start_dt = datetime.fromisoformat(item["start_time"])
                todoist.schedule_task(item["task_id"], start_dt, item["duration_minutes"])
                todoist_updated += 1
            except Exception as exc:
                logger.warning("[planner.confirm] Todoist update failed for %s: %s", item.get("task_id"), exc)

    log_row = (
        user_ctx["supabase"]
        .from_("schedule_log")
        .insert({
            "user_id": user_ctx["user_id"],
            "run_at": datetime.now().isoformat(),
            "schedule_date": target_date.isoformat(),
            "proposed_json": json.dumps(schedule),
            "confirmed": 1,
            "confirmed_at": datetime.now().isoformat(),
            "gcal_event_ids": json.dumps(gcal_event_ids),
            "gcal_write_calendar_id": write_cal_id,
        })
        .execute()
    )
    log_id = (log_row.data or [{}])[0].get("id")

    return {
        "confirmed": True,
        "gcal_events_created": len(gcal_event_ids),
        "todoist_updated": todoist_updated,
        "schedule_log_id": log_id,
    }
