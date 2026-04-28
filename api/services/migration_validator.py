"""
Pure functions for normalising LLM output from the migration parser.

Hard constraints enforced here, not in the prompt — see CLAUDE.md Rule 1
("LLM orchestrates, code enforces"). Snap durations to the blessed
Papyrus set, clamp priorities, drop hallucinated dates, canonicalise
days_of_week, dedupe.

Every function is pure — zero IO, deterministic.
"""
from __future__ import annotations

from datetime import date
from typing import Any

# Blessed Papyrus durations — must match DURATION_LABEL_MAP at
# src/todoist_client.py:19. The migration assistant UI dropdown uses
# the same set; symmetry between LLM output and user options.
BLESSED_DURATIONS: list[int] = [10, 15, 30, 45, 60, 75, 90, 120, 180]
_DEFAULT_DURATION = 30
_DEFAULT_PRIORITY = 3
_VALID_CATEGORIES = {"@deep-work", "@admin", "@quick"}
_CANONICAL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def snap_duration(minutes: int | None) -> int:
    if minutes is None:
        return _DEFAULT_DURATION
    if minutes <= BLESSED_DURATIONS[0]:
        return BLESSED_DURATIONS[0]
    if minutes >= BLESSED_DURATIONS[-1]:
        return BLESSED_DURATIONS[-1]
    # Ties (e.g. 150 between 120 and 180) break toward the shorter
    # duration via Python min()'s left-stability — first blessed
    # value of the closest pair wins.
    return min(BLESSED_DURATIONS, key=lambda b: abs(b - minutes))


def clamp_priority(p: int | None) -> int:
    if p is None:
        return _DEFAULT_PRIORITY
    if p < 1:
        return _DEFAULT_PRIORITY
    if p > 4:
        return 4
    return int(p)


def validate_deadline(value: str | None, today: date) -> str | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed < today:
        return None
    return parsed.isoformat()


def canonicalise_days(days: list[str] | None) -> list[str]:
    if not days:
        return list(_CANONICAL_DAYS)
    seen = set()
    out: list[str] = []
    for d in days:
        if not isinstance(d, str):
            continue
        norm = d.strip().lower()
        if norm in _CANONICAL_DAYS and norm not in seen:
            seen.add(norm)
            out.append(norm)
    if not out:
        return list(_CANONICAL_DAYS)
    # Preserve canonical order regardless of input order.
    return [d for d in _CANONICAL_DAYS if d in seen]


def validate_category(value: str | None) -> str | None:
    if not value:
        return None
    return value if value in _VALID_CATEGORIES else None


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def dedupe_tasks(tasks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for t in tasks:
        key = _norm(t.get("content", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def dedupe_rhythms(rhythms: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in rhythms:
        key = _norm(r.get("name", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _normalise_task(raw: dict, today: date) -> dict | None:
    content = (raw.get("content") or "").strip()
    if not content:
        return None
    return {
        "content": content,
        "priority": clamp_priority(raw.get("priority")),
        "duration_minutes": snap_duration(raw.get("duration_minutes")),
        "category_label": validate_category(raw.get("category_label")),
        "deadline": validate_deadline(raw.get("deadline"), today),
        "reasoning": (raw.get("reasoning") or "").strip(),
    }


def _normalise_rhythm(raw: dict) -> dict | None:
    name = (raw.get("name") or "").strip()
    if not name:
        return None
    sessions = raw.get("sessions_per_week")
    sessions = max(1, min(21, int(sessions) if isinstance(sessions, (int, float)) else 3))
    smin = snap_duration(raw.get("session_min_minutes"))
    smax = snap_duration(raw.get("session_max_minutes"))
    if smin > smax:
        smin, smax = smax, smin
    return {
        "name": name,
        "scheduling_hint": (raw.get("scheduling_hint") or "").strip(),
        "sessions_per_week": sessions,
        "session_min_minutes": smin,
        "session_max_minutes": smax,
        "days_of_week": canonicalise_days(raw.get("days_of_week")),
        "reasoning": (raw.get("reasoning") or "").strip(),
    }


def normalise_proposal(raw: dict[str, Any], today: date) -> dict[str, Any]:
    """Apply every snap/clamp/drop rule. Caller passes `today` for
    deterministic deadline validation in tests."""
    raw_tasks = raw.get("tasks") or []
    raw_rhythms = raw.get("rhythms") or []
    raw_unmatched = raw.get("unmatched") or []

    tasks_clean: list[dict] = []
    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        norm = _normalise_task(t, today)
        if norm is not None:
            tasks_clean.append(norm)

    rhythms_clean: list[dict] = []
    for r in raw_rhythms:
        if not isinstance(r, dict):
            continue
        norm = _normalise_rhythm(r)
        if norm is not None:
            rhythms_clean.append(norm)

    unmatched_clean = [u for u in raw_unmatched if isinstance(u, str) and u.strip()]

    return {
        "tasks": dedupe_tasks(tasks_clean),
        "rhythms": dedupe_rhythms(rhythms_clean),
        "unmatched": unmatched_clean,
    }
