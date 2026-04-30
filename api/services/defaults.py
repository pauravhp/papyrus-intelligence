"""
Default user-config values applied when a user has not explicitly configured
a setting.

Why a separate module: every consumer of the user's config (planner, replan,
future routes that read meal blocks) should see the same defaults rather than
each call site re-implementing what "no daily_blocks set" means. Centralising
here lets a single change propagate everywhere.
"""

from __future__ import annotations

# First-time meal blocks. Applied when the user has no daily_blocks configured.
# A user with an empty daily_blocks list (explicit opt-out) still gets the
# defaults — _ensure_meal_blocks treats both None and [] the same way. If a
# user truly wants "no meal blocks", they can set daily_blocks to a list with
# a single zero-duration entry, but that's an unsupported workflow today.
DEFAULT_MEAL_BLOCKS = [
    {"name": "Breakfast", "start": "08:00", "end": "08:30", "days": "all", "movable": False, "buffer_before_minutes": 0, "buffer_after_minutes": 0},
    {"name": "Lunch",     "start": "12:30", "end": "13:30", "days": "all", "movable": False, "buffer_before_minutes": 0, "buffer_after_minutes": 0},
    {"name": "Dinner",    "start": "18:30", "end": "19:30", "days": "all", "movable": False, "buffer_before_minutes": 0, "buffer_after_minutes": 0},
]


# Sleep / day-shape defaults. compute_free_windows reads these via dict.get,
# which falls back ONLY when the key is missing — an explicit-null value
# bypasses the in-code default and crashes _parse_hm("None") with
# AttributeError: NoneType.strip(). Apply with_sleep_defaults() at config-read
# time to normalise nulls into real values before they reach the scheduler.
DEFAULT_SLEEP: dict = {
    "default_wake_time":       "09:00",
    "morning_buffer_minutes":  90,
    "first_task_not_before":   "10:30",
    "no_tasks_after":          "23:00",
    "weekend_nothing_before":  "13:00",
    "weekend_days":            ["saturday", "sunday"],
}


def with_meal_defaults(config: dict) -> dict:
    """Return a config with daily_blocks defaulted PER-MEAL.

    A user-customised entry for any of Breakfast / Lunch / Dinner is kept
    verbatim. Missing meals are filled in from DEFAULT_MEAL_BLOCKS. This
    matters because the onboarding scan can return a partial list (e.g.
    only Breakfast inferred from morning calendar events) and the planner
    would then schedule tasks during lunch and dinner — caught when
    whodini0407's auto-import plan placed a 30-min meeting straight
    through 18:30-19:30 on 2026-04-30.

    Non-meal user blocks (e.g. "Reading time") are preserved alongside.
    """
    user_blocks: list[dict] = list(config.get("daily_blocks") or [])
    have_names = {b.get("name", "").lower() for b in user_blocks}
    for default in DEFAULT_MEAL_BLOCKS:
        if default["name"].lower() not in have_names:
            user_blocks.append(dict(default))
    return {**config, "daily_blocks": user_blocks}


def with_sleep_defaults(config: dict) -> dict:
    """Return a config whose sleep dict has every required field non-null.

    Per-field merge (not dict-level): a partial sleep dict with one null
    sibling keeps the user's other values and only fills the null fields.
    Missing keys and None values are treated identically — both fall back
    to DEFAULT_SLEEP.
    """
    user_sleep = config.get("sleep") or {}

    def _pick(key, default):
        value = user_sleep.get(key)
        # None, empty string, and empty list all fall back. The empty string
        # case shows up when a user clears a time field in /settings/schedule
        # — the form persists "" rather than removing the key.
        if value is None or value == "" or value == []:
            return default
        return value

    merged = {key: _pick(key, default) for key, default in DEFAULT_SLEEP.items()}
    # Preserve any extra fields the user has set that we don't enumerate
    # in DEFAULT_SLEEP (e.g. default_sleep_time, late_night_threshold).
    for key, value in user_sleep.items():
        if key not in merged and value is not None:
            merged[key] = value
    return {**config, "sleep": merged}
