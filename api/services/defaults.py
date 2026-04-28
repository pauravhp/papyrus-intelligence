"""
Default user-config values applied when a user has not explicitly configured
a setting.

Why a separate module: every consumer of the user's config (planner, replan,
future routes that read meal blocks) should see the same defaults rather than
each call site re-implementing what "no daily_blocks set" means. Centralising
here lets a single change propagate everywhere.

Currently only meal-block defaults live here. Other defaults (sleep cutoff,
min_gap, etc.) are still inlined at their consumers since they have only one
reader; once a second consumer appears, lift the default into this module.
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


def with_meal_defaults(config: dict) -> dict:
    """Return a config with daily_blocks defaulted if the user hasn't set any.

    Returns the original dict unchanged when daily_blocks is non-empty so the
    user's explicit configuration always wins.
    """
    if config.get("daily_blocks"):
        return config
    return {**config, "daily_blocks": list(DEFAULT_MEAL_BLOCKS)}
