import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-todoist-client-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-todoist-client-secret")

from unittest.mock import MagicMock, patch
import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user_ctx(coaching_enabled=True, disabled_types=None):
    return {
        "user_id": "user-123",
        "config": {
            "nudges": {
                "coaching_enabled": coaching_enabled,
                "disabled_types": disabled_types or [],
            }
        },
        "todoist_api_key": None,
    }

def _make_signals(overrides=None):
    """Return a signals dict with all keys set to safe defaults (no nudge fires)."""
    base = {
        "most_pushed_task_id": None,
        "most_pushed_task_name": None,
        "most_pushed_task_count": 0,
        "completion_rate_7d": 1.0,
        "completed_tasks_7d": 5,
        "hours_scheduled_today": 2.0,
        "task_count_today": 4,
        "avg_block_duration_today_minutes": 60,
        "deep_work_tasks_in_trough": 0,
        "daily_completion_streak": 0,
        "overdue_count": 0,
        "overdue_count_7d_ago": 0,
        "stale_waiting_task_id": None,
        "stale_waiting_task_name": None,
        "stale_waiting_task_days": 0,
        "rhythms_without_end_date_count": 0,
        "rhythms_without_end_date_first_name": None,
        "rhythms_without_end_date_first_id": None,
        "backlog_growth_rate": 0.0,
        "backlog_delta": 0,
        "habit_skipped_rhythm_id": None,
        "habit_skipped_rhythm_name": None,
        "estimation_accuracy_7d": 0.5,
        "dismissed_set": set(),
        "push_count_by_task_id": {},
        "task_map": {},
    }
    if overrides:
        base.update(overrides)
    return base


# ── get_eligible guards ───────────────────────────────────────────────────────

def test_get_eligible_returns_none_for_mid_conversation():
    from api.services.nudge_service import get_eligible
    ctx = _make_user_ctx()
    messages = [
        {"role": "user", "content": "plan my day"},
        {"role": "assistant", "content": "here is your schedule"},
    ]
    result = get_eligible(ctx, messages)
    assert result is None


def test_get_eligible_returns_none_when_coaching_disabled():
    from api.services.nudge_service import get_eligible
    ctx = _make_user_ctx(coaching_enabled=False)
    with patch("api.services.nudge_service._compute_signals") as mock_signals:
        result = get_eligible(ctx, [{"role": "user", "content": "plan"}])
    mock_signals.assert_not_called()
    assert result is None


# ── _condition_met ────────────────────────────────────────────────────────────

def test_condition_met_repeated_deferral():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({"most_pushed_task_count": 3, "most_pushed_task_name": "Figma redesign"})
    assert _condition_met(nudge, signals) is True

def test_condition_not_met_repeated_deferral():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({"most_pushed_task_count": 2})
    assert _condition_met(nudge, signals) is False

def test_condition_met_over_scheduling():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "over_scheduling")
    signals = _make_signals({"completion_rate_7d": 0.50})
    assert _condition_met(nudge, signals) is True

def test_condition_not_met_over_scheduling():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "over_scheduling")
    signals = _make_signals({"completion_rate_7d": 0.75})
    assert _condition_met(nudge, signals) is False

def test_condition_met_no_deadline():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "no_deadline")
    signals = _make_signals({"rhythms_without_end_date_count": 2, "rhythms_without_end_date_first_name": "Daily writing"})
    assert _condition_met(nudge, signals) is True

def test_condition_met_context_switching():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "context_switching")
    signals = _make_signals({"avg_block_duration_today_minutes": 20, "task_count_today": 8})
    assert _condition_met(nudge, signals) is True

def test_condition_not_met_context_switching_few_tasks():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "context_switching")
    # Short blocks but not enough tasks
    signals = _make_signals({"avg_block_duration_today_minutes": 20, "task_count_today": 5})
    assert _condition_met(nudge, signals) is False

def test_condition_met_backlog_growing():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "backlog_growing")
    signals = _make_signals({"backlog_growth_rate": 0.30, "overdue_count": 8, "backlog_delta": 3})
    assert _condition_met(nudge, signals) is True

def test_condition_met_no_breaks():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "no_breaks_scheduled")
    signals = _make_signals({"hours_scheduled_today": 5.0})
    assert _condition_met(nudge, signals) is True

def test_condition_met_completion_streak():
    from api.services.nudge_service import _condition_met, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "completion_streak")
    signals = _make_signals({"daily_completion_streak": 4})
    assert _condition_met(nudge, signals) is True


# ── _is_dismissed ─────────────────────────────────────────────────────────────

def test_is_dismissed_returns_false_when_no_dismissals():
    from api.services.nudge_service import _is_dismissed, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({"most_pushed_task_id": "task-abc", "dismissed_set": set()})
    assert _is_dismissed("user-123", nudge, signals) is False

def test_is_dismissed_per_instance():
    from api.services.nudge_service import _is_dismissed, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({
        "most_pushed_task_id": "task-abc",
        "dismissed_set": {("repeated_deferral", "task-abc")},
    })
    assert _is_dismissed("user-123", nudge, signals) is True

def test_is_dismissed_per_type():
    from api.services.nudge_service import _is_dismissed, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({
        "most_pushed_task_id": "task-xyz",
        "dismissed_set": {("repeated_deferral", "__type__")},
    })
    assert _is_dismissed("user-123", nudge, signals) is True


# ── _build_nudge_card ─────────────────────────────────────────────────────────

def test_build_nudge_card_repeated_deferral():
    from api.services.nudge_service import _build_nudge_card, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "repeated_deferral")
    signals = _make_signals({
        "most_pushed_task_id": "task-abc",
        "most_pushed_task_name": "Figma redesign",
        "most_pushed_task_count": 4,
    })
    card = _build_nudge_card(nudge, signals)
    assert card.nudge_id == "repeated_deferral"
    assert "Figma redesign" in card.coach_message
    assert "4" in card.coach_message
    assert card.action_label == "Set a deadline"
    assert card.instance_key == "task-abc"
    assert card.learn_more_path == "/learn/repeated-deferral"

def test_build_nudge_card_completion_streak_no_action():
    from api.services.nudge_service import _build_nudge_card, NUDGE_CATALOG
    nudge = next(n for n in NUDGE_CATALOG if n["nudge_id"] == "completion_streak")
    signals = _make_signals({"daily_completion_streak": 5})
    card = _build_nudge_card(nudge, signals)
    assert card.nudge_id == "completion_streak"
    assert "5" in card.coach_message
    assert card.action_label is None
    assert card.instance_key is None


# ── Priority + positive-nudge suppression ─────────────────────────────────────

def test_positive_nudge_suppressed_when_warning_eligible():
    from api.services.nudge_service import _select_nudge, NUDGE_CATALOG
    # Signals that trigger both a warning (over_scheduling) and a positive (completion_streak)
    signals = _make_signals({
        "completion_rate_7d": 0.40,
        "daily_completion_streak": 5,
    })
    disabled_types = []
    result = _select_nudge(signals, disabled_types)
    assert result is not None
    assert result["nudge_id"] == "over_scheduling"

def test_positive_nudge_fires_when_no_warning_eligible():
    from api.services.nudge_service import _select_nudge, NUDGE_CATALOG
    signals = _make_signals({"daily_completion_streak": 5})
    disabled_types = []
    result = _select_nudge(signals, disabled_types)
    assert result is not None
    assert result["nudge_id"] == "completion_streak"

def test_disabled_type_skipped():
    from api.services.nudge_service import _select_nudge, NUDGE_CATALOG
    signals = _make_signals({"most_pushed_task_count": 5, "daily_completion_streak": 5})
    result = _select_nudge(signals, disabled_types=["repeated_deferral"])
    # repeated_deferral is disabled, completion_streak is positive — no warnings → completion_streak fires
    assert result is not None
    assert result["nudge_id"] == "completion_streak"
