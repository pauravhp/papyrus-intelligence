from __future__ import annotations

from datetime import date

from api.services.migration_validator import (
    BLESSED_DURATIONS,
    snap_duration,
    clamp_priority,
    validate_deadline,
    canonicalise_days,
    validate_category,
    dedupe_tasks,
    dedupe_rhythms,
    normalise_proposal,
)


def test_blessed_duration_set():
    assert BLESSED_DURATIONS == [10, 15, 30, 45, 60, 75, 90, 120, 180]


def test_snap_duration_to_nearest_blessed():
    assert snap_duration(0) == 10            # below floor → floor
    assert snap_duration(7) == 10            # round to 10
    assert snap_duration(20) == 15           # 15 closer than 30
    assert snap_duration(40) == 45
    assert snap_duration(70) == 75
    assert snap_duration(100) == 90          # 90 closer than 120
    assert snap_duration(150) == 120         # 120 closer than 180
    assert snap_duration(999) == 180         # above ceiling → ceiling
    assert snap_duration(None) == 30         # default when missing


def test_clamp_priority():
    assert clamp_priority(1) == 1
    assert clamp_priority(4) == 4
    assert clamp_priority(0) == 3            # below → default
    assert clamp_priority(5) == 4            # above → ceiling
    assert clamp_priority(None) == 3         # missing → default


def test_validate_deadline():
    today = date(2026, 4, 27)
    assert validate_deadline("2026-04-27", today) == "2026-04-27"
    assert validate_deadline("2026-12-01", today) == "2026-12-01"
    assert validate_deadline("2026-04-26", today) is None    # past
    assert validate_deadline("not-a-date", today) is None
    assert validate_deadline(None, today) is None


def test_canonicalise_days():
    assert canonicalise_days(["Mon", "TUE", "wed"]) == ["mon", "tue", "wed"]
    assert canonicalise_days(["xyz", "fri"]) == ["fri"]
    assert canonicalise_days([]) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert canonicalise_days(None) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_validate_category():
    assert validate_category("@deep-work") == "@deep-work"
    assert validate_category("@admin") == "@admin"
    assert validate_category("@quick") == "@quick"
    assert validate_category(None) is None
    assert validate_category("@made-up") is None
    assert validate_category("deep-work") is None    # missing @


def test_dedupe_tasks_by_normalised_content():
    tasks = [
        {"content": "Email Sarah", "priority": 3, "duration_minutes": 15},
        {"content": "  email sarah ", "priority": 4, "duration_minutes": 30},
        {"content": "Other task", "priority": 3, "duration_minutes": 30},
    ]
    out = dedupe_tasks(tasks)
    assert len(out) == 2
    assert out[0]["content"] == "Email Sarah"   # first wins


def test_dedupe_rhythms_by_normalised_name():
    rhythms = [
        {"name": "Morning workout", "sessions_per_week": 5},
        {"name": "morning workout", "sessions_per_week": 3},
    ]
    out = dedupe_rhythms(rhythms)
    assert len(out) == 1
    assert out[0]["name"] == "Morning workout"


def test_normalise_proposal_drops_empty_content():
    raw = {
        "tasks": [
            {"content": "", "priority": 3, "duration_minutes": 30},
            {"content": "Real task", "priority": 3, "duration_minutes": 30},
        ],
        "rhythms": [{"name": "", "sessions_per_week": 3}],
        "unmatched": ["a stray line"],
    }
    out = normalise_proposal(raw, today=date(2026, 4, 27))
    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["content"] == "Real task"
    assert out["rhythms"] == []
    assert out["unmatched"] == ["a stray line"]


def test_normalise_proposal_swaps_min_max_when_reversed():
    raw = {
        "tasks": [],
        "rhythms": [{
            "name": "Run",
            "sessions_per_week": 3,
            "session_min_minutes": 90,
            "session_max_minutes": 30,
            "days_of_week": ["mon"],
        }],
        "unmatched": [],
    }
    out = normalise_proposal(raw, today=date(2026, 4, 27))
    rh = out["rhythms"][0]
    assert rh["session_min_minutes"] == 30
    assert rh["session_max_minutes"] == 90


def test_clamp_priority_coerces_float_to_int():
    assert clamp_priority(3.0) == 3
    assert clamp_priority(2.7) == 2  # int() truncates — explicitly the contract
    assert isinstance(clamp_priority(3.0), int)


def test_normalise_proposal_silently_skips_non_dict_items():
    raw = {
        "tasks": ["a stray string", 42, {"content": "Real task", "priority": 3, "duration_minutes": 30}],
        "rhythms": [None, {"name": "Run", "sessions_per_week": 3, "session_min_minutes": 30, "session_max_minutes": 60, "days_of_week": ["mon"]}],
        "unmatched": [],
    }
    out = normalise_proposal(raw, today=date(2026, 4, 27))
    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["content"] == "Real task"
    assert len(out["rhythms"]) == 1
    assert out["rhythms"][0]["name"] == "Run"


def test_canonicalise_days_returns_canonical_order_regardless_of_input():
    assert canonicalise_days(["fri", "mon"]) == ["mon", "fri"]
    assert canonicalise_days(["sun", "wed", "tue"]) == ["tue", "wed", "sun"]
