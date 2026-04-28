import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock, patch
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from src.models import FreeWindow, TodoistTask


def _make_tasks():
    tz = ZoneInfo("America/Vancouver")
    return [
        TodoistTask(
            id="t1", content="Write report", project_id="p1",
            priority=3, due_datetime=None, deadline=None,
            duration_minutes=90, labels=[], is_inbox=True,
        )
    ]


def _make_windows():
    tz = ZoneInfo("America/Vancouver")
    return [
        FreeWindow(
            start=datetime(2026, 4, 12, 9, 0, tzinfo=tz),
            end=datetime(2026, 4, 12, 10, 30, tzinfo=tz),
            duration_minutes=90,
            block_type="morning",
        )
    ]


def _make_config():
    return {"user": {"timezone": "America/Vancouver"}, "sleep": {}, "rules": {"hard": [], "soft": []}}


def test_schedule_day_returns_structured_output():
    """schedule_day returns scheduled list + pushed list + reasoning_summary."""
    from api.services.schedule_service import schedule_day

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text='{"scheduled":[{"task_id":"t1","task_name":"Write report","start_time":"2026-04-12T09:00:00-07:00","end_time":"2026-04-12T10:30:00-07:00","duration_minutes":90}],"pushed":[],"reasoning_summary":"All scheduled."}')]

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = schedule_day(
            tasks=_make_tasks(),
            free_windows=_make_windows(),
            config=_make_config(),
            context_note="normal day",
            anthropic_api_key="sk-ant-test",
            target_date="2026-04-12",
        )

    assert "scheduled" in result
    assert len(result["scheduled"]) == 1
    assert result["scheduled"][0]["task_id"] == "t1"
    assert "pushed" in result
    assert "reasoning_summary" in result


def test_schedule_day_retries_on_invalid_json():
    """schedule_day retries once on JSON parse failure, raises RuntimeError on second."""
    from api.services.schedule_service import schedule_day

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="not json at all")]

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        with pytest.raises(RuntimeError, match="invalid JSON"):
            schedule_day(
                tasks=_make_tasks(),
                free_windows=_make_windows(),
                config=_make_config(),
                context_note="",
                anthropic_api_key="sk-ant-test",
                target_date="2026-04-12",
            )


def test_build_prompt_shows_gcal_events():
    """_build_prompt must include a CALENDAR EVENTS section so the LLM knows
    what is already on the user's calendar and why certain times are blocked."""
    from api.services.schedule_service import _build_prompt
    from src.models import CalendarEvent
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("America/Vancouver")
    event = CalendarEvent(
        id="e1", summary="Team Standup",
        start=datetime(2026, 4, 15, 9, 0, tzinfo=TZ),
        end=datetime(2026, 4, 15, 9, 30, tzinfo=TZ),
        color_id=None, is_all_day=False,
    )
    prompt = _build_prompt([], [], {}, "", "2026-04-15", events=[event])
    assert "Team Standup" in prompt
    assert "09:00" in prompt
    assert "09:30" in prompt


def test_build_prompt_shows_session_range_for_budget_task():
    from src.models import TodoistTask, FreeWindow
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from api.services.schedule_service import _build_prompt

    tz = ZoneInfo("America/Vancouver")
    task = TodoistTask(
        id="proj_1",
        content="App Side Project",
        project_id="none",
        priority=3,
        due_datetime=None,
        deadline=None,
        duration_minutes=90,
        labels=[],
        is_inbox=False,
        is_rhythm=True,
        session_max_minutes=180,
        sessions_per_week=2,
    )
    window = FreeWindow(
        start=datetime(2026, 4, 13, 9, 0, tzinfo=tz),
        end=datetime(2026, 4, 13, 12, 0, tzinfo=tz),
        duration_minutes=180,
        block_type="morning",
    )
    prompt = _build_prompt([task], [window], {}, "", "2026-04-13")
    assert "90-180min" in prompt
    assert "[2x/week]" in prompt
    assert "proj_1" in prompt


def test_schedule_day_filters_no_duration_and_surfaces_them_in_pushed():
    """
    Tasks with duration_minutes=None are kept out of the LLM prompt and
    surfaced in the result's `pushed` list with an actionable reason.

    Regression guard for 2026-04-24: previously these tasks rendered as
    "Nonem" in the prompt and bloated the response with 20+ pushed entries,
    causing JSON truncation at max_tokens.
    """
    from unittest.mock import patch, MagicMock
    from src.models import TodoistTask, FreeWindow
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from api.services.schedule_service import schedule_day

    tz = ZoneInfo("America/Vancouver")

    def _t(tid, content, dur):
        return TodoistTask(
            id=tid, content=content, project_id="p", priority=3,
            due_datetime=None, deadline=None, duration_minutes=dur,
            labels=[], is_inbox=False, is_rhythm=False,
        )

    tasks = [_t("a", "Has duration", 60), _t("b", "No duration", None), _t("c", "Also none", None)]
    window = FreeWindow(
        start=datetime(2026, 4, 24, 14, 0, tzinfo=tz),
        end=datetime(2026, 4, 24, 18, 0, tzinfo=tz),
        duration_minutes=240,
        block_type="afternoon",
    )

    captured_prompt = {}
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text='{"scheduled":[{"task_id":"a","task_name":"Has duration","start_time":"2026-04-24T14:00:00-07:00","end_time":"2026-04-24T15:00:00-07:00","duration_minutes":60,"category":"deep_work"}],"pushed":[],"reasoning_summary":"ok"}')]

    fake_messages = MagicMock()
    fake_messages.create.return_value = fake_resp

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages = fake_messages
        result = schedule_day(
            tasks=tasks, free_windows=[window], config={}, context_note="",
            anthropic_api_key="sk-ant-test", target_date="2026-04-24",
        )

    # 1. The LLM only saw the schedulable task — "Nonem" never appears in prompt
    sent_prompt = fake_messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Nonem" not in sent_prompt
    assert "No duration" not in sent_prompt  # task content stripped from prompt
    assert "Has duration" in sent_prompt

    # 2. max_tokens >= 4096 so large responses don't truncate mid-string
    assert fake_messages.create.call_args.kwargs["max_tokens"] >= 4096

    # 3. No-duration tasks appear in pushed with an actionable reason
    pushed_ids = {p["task_id"] for p in result["pushed"]}
    assert pushed_ids == {"b", "c"}
    for p in result["pushed"]:
        assert "duration" in p["reason"].lower()


# ── Reasoning-summary leak filter (item #15) ──────────────────────────────────


@pytest.mark.parametrize("leak", [
    "Stacked your focus blocks into the 220-minute window before your cutoff.",
    "Front-loaded the 90-min block this morning.",
    "Scheduled 4 tasks adding to 135m before your cutoff.",
    "Your 3 hours of focus work goes first.",
    "Placed it in the 45 minute slot.",
    "Used the 2hr afternoon stretch for deep work.",
    "Scheduled 6gJjJ7M3 (60m) in the morning.",  # task-id + duration — duration is the leak
])
def test_sanitize_reasoning_summary_drops_leaked_phrasings(leak):
    """Numeric durations like \"the 220-minute window\" or \"adding to 135m\"
    are internal scheduler arithmetic — Haiku occasionally leaks them into
    coach voice. The Python sanitizer is the final defence."""
    from api.services.schedule_service import _sanitize_reasoning_summary
    assert _sanitize_reasoning_summary(leak) == ""


@pytest.mark.parametrize("clean", [
    "Stacked your focus blocks into the late-night window before your cutoff.",
    "Front-loaded the deep work this morning so admin tasks fall into the afternoon.",
    "Shifted things by an hour to clear the morning.",
    "",
    # Regression cases — these used to be wrongly dropped by over-aggressive
    # patterns (priority-code and underscore-token). They MUST round-trip.
    # Real reasoning_summary from a 2026-04-28 plan call: matched on `p1`
    # and was silently nuked, leaving the user staring at an empty panel.
    "I front-loaded your p1 task in the early window, stacked admin work "
    "into the afternoon slots around your lunch and dinner blocks, and "
    "pushed the deep-work crypto task into your late-night window where "
    "you have the most uninterrupted time. The rhythm tasks and remaining "
    "admin items didn't fit within your cutoff, so they're queued for "
    "another day.",
    "Slotted your P2 admin tasks around the gym block.",
    "Front-loaded the deep-work block this morning.",  # kebab-case, fine
])
def test_sanitize_reasoning_summary_passes_clean_coach_text(clean):
    """Clean coach voice round-trips unchanged. Specifically: priority codes
    (p1/P2/etc), kebab-case category names (\"deep-work\"), and verbal time
    references (\"by an hour\") are all legitimate coach copy and must NOT
    be filtered. Only the digit+time-unit pattern is policy."""
    from api.services.schedule_service import _sanitize_reasoning_summary
    assert _sanitize_reasoning_summary(clean) == clean


def test_schedule_day_strips_leaked_summary_from_llm_output():
    """End-to-end: when the LLM (mocked) returns a summary containing a
    duration total, schedule_day's response surfaces an empty summary rather
    than leaking the phrasing through to the client."""
    from api.services.schedule_service import schedule_day

    leaked = '{"scheduled":[],"pushed":[],"reasoning_summary":"Stacked focus into the 220-minute window."}'
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=leaked)]

    with patch("api.services.schedule_service.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = schedule_day(
            tasks=_make_tasks(),
            free_windows=_make_windows(),
            config=_make_config(),
            context_note="",
            anthropic_api_key="sk-ant-test",
            target_date="2026-04-12",
        )

    assert result["reasoning_summary"] == ""


# ── Captured-prompt fixture (Lane E) ──────────────────────────────────────────
#
# Centralised helper for asserting that specific config fields, task metadata,
# and rules appear verbatim in the prompt the LLM receives. The plan, refine,
# and replan paths all converge on _build_prompt — by exercising it through
# realistic inputs we catch silent prompt regressions without needing a live
# LLM call.


def _rhythm_task(tid="proj_42", name="Yoga", hint="mornings only", duration=30, max_dur=60, per_week=3):
    """A synthetic rhythm task as _inject_synthetic_rhythms produces it.
    `content` is the bare rhythm_name (user-facing) and the placement hint
    travels in `rhythm_hint` (LLM-only — never rendered in task_name)."""
    return TodoistTask(
        id=tid, content=name, project_id="rhythm", priority=2,
        due_datetime=None, deadline=None, duration_minutes=duration,
        labels=[], is_inbox=False, is_rhythm=True,
        session_max_minutes=max_dur, sessions_per_week=per_week,
        rhythm_hint=hint,
    )


def _full_config():
    """A user with every config knob filled in — used to assert each one
    surfaces in the rendered prompt."""
    return {
        "user": {"timezone": "America/Vancouver"},
        "sleep": {"no_tasks_after": "22:30"},
        "rules": {"hard": ["Never schedule before 8am", "No back-to-back deep work"]},
        "scheduling": {"min_gap_between_tasks_minutes": 25},
        "daily_blocks": [
            {"name": "Breakfast", "start": "08:00", "end": "08:30"},
            {"name": "Lunch", "start": "12:30", "end": "13:30"},
            {"name": "Dinner", "start": "18:30", "end": "19:30"},
        ],
    }


def test_capture_prompt_fresh_user_minimal_config():
    """A fresh user with the bare minimum config (timezone only) renders a
    valid prompt without crashing — and core sections still appear so the LLM
    has something to work with."""
    from api.services.schedule_service import _build_prompt

    config = {"user": {"timezone": "America/Vancouver"}}
    prompt = _build_prompt(_make_tasks(), _make_windows(), config, "", "2026-04-12")

    assert "TASKS" in prompt
    assert "SUGGESTED WINDOWS" in prompt
    assert "HARD RULES" in prompt
    # Min gap default (10) when no scheduling.min_gap_between_tasks_minutes set
    assert "10 minutes between" in prompt


def test_capture_prompt_full_config_surfaces_every_knob():
    """Every config field a user can set must appear in the prompt — otherwise
    the LLM has no way to honor it."""
    from api.services.schedule_service import _build_prompt

    prompt = _build_prompt(_make_tasks(), _make_windows(), _full_config(), "", "2026-04-12")

    # min_gap_between_tasks_minutes
    assert "25 minutes between" in prompt
    # hard rules
    assert "Never schedule before 8am" in prompt
    assert "No back-to-back deep work" in prompt
    # daily_blocks (each meal renders as soft block)
    assert "Breakfast 08:00–08:30" in prompt
    assert "Lunch 12:30–13:30" in prompt
    assert "Dinner 18:30–19:30" in prompt
    # cutoff (user explicitly set no_tasks_after)
    assert "22:30" in prompt


def test_capture_prompt_rhythm_hint_appears_in_plan():
    """A rhythm with a scheduling hint must surface verbatim in the prompt's
    TASKS line so the scheduler can honor it. The hint travels through
    `rhythm_hint` (structured) — never embedded in content/task_name — so
    long names + long hints can't truncate it away."""
    from api.services.schedule_service import _build_prompt

    task = _rhythm_task(name="Yoga", hint="mornings only")
    prompt = _build_prompt([task], _make_windows(), _make_config(), "", "2026-04-12")

    assert "mornings only" in prompt
    assert "[rhythm]" in prompt
    assert "[hint: mornings only]" in prompt


def test_capture_prompt_rhythm_hint_long_name_does_not_truncate_hint():
    """REGRESSION: with the hint embedded in content, a long rhythm name
    plus the hint exceeded the 50-char content cap and the hint got
    silently truncated. Now the hint is structured, so this can't happen."""
    from api.services.schedule_service import _build_prompt

    task = _rhythm_task(
        name="Side Project: Reading and Thinking About Architecture",
        hint="mornings only",
    )
    prompt = _build_prompt([task], _make_windows(), _make_config(), "", "2026-04-12")
    assert "[hint: mornings only]" in prompt


def test_rhythm_task_name_does_not_leak_hint_to_response():
    """The rhythm hint must not appear in `content` (the field that becomes
    task_name in the response and the GCal event title). It belongs in the
    LLM prompt only."""
    task = _rhythm_task(name="Yoga", hint="mornings only")
    # content is the user-facing label — clean
    assert task.content == "Yoga"
    assert ":" not in task.content
    # the hint lives on the dedicated internal field
    assert task.rhythm_hint == "mornings only"


def test_capture_prompt_rhythm_hint_persists_in_refine():
    """REGRESSION: the refine-pipeline must not strip the rhythm hint between
    plan and refine. The hint is the only signal the LLM has for a rhythm's
    placement preference; losing it on refine moves the rhythm out of its
    preferred window.

    This goes through the full planner.run_schedule_pipeline so we catch
    bugs in HOW rhythms are wired into the prompt, not just in _build_prompt."""
    from datetime import date
    from src.models import FreeWindow
    from api.services.schedule_service import _build_prompt
    from api.services import planner
    from api.services.extractor import ExtractionResult

    tz = ZoneInfo("America/Vancouver")
    today = date.today()
    window = FreeWindow(
        start=datetime(today.year, today.month, today.day, 9, 0, tzinfo=tz),
        end=datetime(today.year, today.month, today.day, 12, 0, tzinfo=tz),
        duration_minutes=180, block_type="morning",
    )

    config = {
        "user": {"timezone": "America/Vancouver"},
        "rules": {"hard": []},
        "daily_blocks": [],
        "source_calendar_ids": ["primary"],
    }
    user_ctx = {
        "user_id": "u-1", "config": config, "todoist_api_key": "tok",
        "gcal_service": None, "supabase": MagicMock(),
        "anthropic_api_key": "sk-ant-test",
    }

    rhythm_row = {
        "id": 42, "rhythm_name": "Yoga", "description": "mornings only",
        "sessions_per_week": 3, "session_min_minutes": 30, "session_max_minutes": 60,
    }

    captured = {}
    def fake_schedule_day(**kwargs):
        # Re-render the prompt with the same inputs — that's what the LLM saw.
        prompt = _build_prompt(
            kwargs["tasks"], kwargs["free_windows"], kwargs["config"],
            kwargs["context_note"], kwargs["target_date"], events=kwargs.get("events"),
        )
        captured.setdefault("prompts", []).append(prompt)
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    common_patches = [
        patch("api.services.planner.TodoistClient", return_value=mock_todoist),
        patch("api.services.planner.get_events", return_value=[]),
        patch("api.services.planner.compute_free_windows", return_value=[window]),
        patch("api.services.planner.get_active_rhythms", return_value=[rhythm_row]),
        patch("api.services.planner.extract_constraints",
              return_value=ExtractionResult(blocks=[], cutoff_override_iso=None)),
        patch("api.services.planner.schedule_day", side_effect=fake_schedule_day),
        patch("api.services.planner._compute_rhythm_sessions_done_this_week", return_value={}),
        patch("api.services.planner._load_self_written_event_ids", return_value=set()),
    ]
    for p in common_patches:
        p.start()
    try:
        # Plan
        planner.plan(user_ctx, today, "")
        # Refine — same context, just adds a previous_proposal baseline
        previous_proposal = {
            "scheduled": [{
                "task_id": "proj_42", "task_name": "Yoga: mornings only",
                "start_time": f"{today.isoformat()}T09:00:00-07:00",
                "end_time": f"{today.isoformat()}T09:30:00-07:00",
                "duration_minutes": 30, "category": "admin",
            }],
            "pushed": [], "blocks": [], "cutoff_override": None,
        }
        planner.refine(user_ctx, today, previous_proposal=previous_proposal,
                       refinement_message="bump everything 30 min later")
    finally:
        for p in common_patches:
            p.stop()

    assert len(captured.get("prompts", [])) == 2, "expected one schedule_day call per planner entry point"
    plan_prompt, refine_prompt = captured["prompts"]
    assert "mornings only" in plan_prompt, "plan prompt missing rhythm hint"
    assert "mornings only" in refine_prompt, (
        "refine prompt missing rhythm hint — the LLM has no signal to honor "
        "the rhythm's placement preference and moves it to a non-morning slot"
    )


def test_capture_prompt_replan_path_includes_rules_and_meals():
    """The replan path runs through the same _build_prompt entry point as
    plan/refine; we verify the same config knobs surface there too."""
    from datetime import date
    from src.models import FreeWindow
    from api.services.schedule_service import _build_prompt
    from api.services import planner
    from api.services.extractor import ExtractionResult

    tz = ZoneInfo("America/Vancouver")
    today = date.today()
    window = FreeWindow(
        start=datetime(today.year, today.month, today.day, 14, 0, tzinfo=tz),
        end=datetime(today.year, today.month, today.day, 18, 0, tzinfo=tz),
        duration_minutes=240, block_type="afternoon",
    )

    user_ctx = {
        "user_id": "u-1", "config": _full_config(), "todoist_api_key": "tok",
        "gcal_service": None, "supabase": MagicMock(),
        "anthropic_api_key": "sk-ant-test",
    }

    captured = {}
    def fake_schedule_day(**kwargs):
        prompt = _build_prompt(
            kwargs["tasks"], kwargs["free_windows"], kwargs["config"],
            kwargs["context_note"], kwargs["target_date"], events=kwargs.get("events"),
        )
        captured["prompt"] = prompt
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    common_patches = [
        patch("api.services.planner.TodoistClient", return_value=mock_todoist),
        patch("api.services.planner.get_events", return_value=[]),
        patch("api.services.planner.compute_free_windows", return_value=[window]),
        patch("api.services.planner.get_active_rhythms", return_value=[]),
        patch("api.services.planner.extract_constraints",
              return_value=ExtractionResult(blocks=[], cutoff_override_iso=None)),
        patch("api.services.planner.schedule_day", side_effect=fake_schedule_day),
        patch("api.services.planner._compute_rhythm_sessions_done_this_week", return_value={}),
        patch("api.services.planner._load_self_written_event_ids", return_value=set()),
    ]
    for p in common_patches:
        p.start()
    try:
        candidate = TodoistTask(
            id="t1", content="Backlog task", project_id="p", priority=3,
            due_datetime=None, deadline=None, duration_minutes=60,
            labels=[], is_inbox=False, is_rhythm=False,
        )
        planner.replan(user_ctx, today, candidate_tasks=[candidate], prose="afternoon replan")
    finally:
        for p in common_patches:
            p.stop()

    prompt = captured["prompt"]
    assert "25 minutes between" in prompt
    assert "Lunch 12:30–13:30" in prompt
    assert "Never schedule before 8am" in prompt
    assert "22:30" in prompt


# ── Item 4: meal-block defaults for first-time users ─────────────────────────


def test_first_time_user_gets_default_meal_blocks_in_prompt():
    """A user with no daily_blocks configured must still see breakfast/lunch/
    dinner as soft blocks in the prompt — otherwise the scheduler cheerfully
    plans 12pm coding sessions and the user finds out they've worked through
    lunch every day."""
    from datetime import date
    from src.models import FreeWindow
    from api.services.schedule_service import _build_prompt
    from api.services import planner
    from api.services.extractor import ExtractionResult

    tz = ZoneInfo("America/Vancouver")
    today = date.today()
    window = FreeWindow(
        start=datetime(today.year, today.month, today.day, 9, 0, tzinfo=tz),
        end=datetime(today.year, today.month, today.day, 17, 0, tzinfo=tz),
        duration_minutes=480, block_type="day",
    )

    fresh_config = {
        "user": {"timezone": "America/Vancouver"},
        "rules": {"hard": []},
        # No daily_blocks set — fresh user, defaults must apply
        "source_calendar_ids": ["primary"],
    }
    user_ctx = {
        "user_id": "u-1", "config": fresh_config, "todoist_api_key": "tok",
        "gcal_service": None, "supabase": MagicMock(),
        "anthropic_api_key": "sk-ant-test",
    }

    captured = {}
    def fake_schedule_day(**kwargs):
        captured["prompt"] = _build_prompt(
            kwargs["tasks"], kwargs["free_windows"], kwargs["config"],
            kwargs["context_note"], kwargs["target_date"], events=kwargs.get("events"),
        )
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    common_patches = [
        patch("api.services.planner.TodoistClient", return_value=mock_todoist),
        patch("api.services.planner.get_events", return_value=[]),
        patch("api.services.planner.compute_free_windows", return_value=[window]),
        patch("api.services.planner.get_active_rhythms", return_value=[]),
        patch("api.services.planner.extract_constraints",
              return_value=ExtractionResult(blocks=[], cutoff_override_iso=None)),
        patch("api.services.planner.schedule_day", side_effect=fake_schedule_day),
        patch("api.services.planner._compute_rhythm_sessions_done_this_week", return_value={}),
        patch("api.services.planner._load_self_written_event_ids", return_value=set()),
    ]
    for p in common_patches:
        p.start()
    try:
        planner.plan(user_ctx, today, "")
    finally:
        for p in common_patches:
            p.stop()

    prompt = captured["prompt"]
    assert "Breakfast 08:00–08:30" in prompt
    assert "Lunch 12:30–13:30" in prompt
    assert "Dinner 18:30–19:30" in prompt


def test_with_meal_defaults_helper_returns_unchanged_when_user_set():
    """The helper must not clobber a user's explicit daily_blocks."""
    from api.services.defaults import with_meal_defaults

    user_blocks = [{"name": "Brunch", "start": "11:00", "end": "12:30"}]
    cfg = {"daily_blocks": user_blocks}
    out = with_meal_defaults(cfg)
    # Same blocks object; user wins
    assert out["daily_blocks"] == user_blocks


def test_with_meal_defaults_helper_fills_in_for_empty_config():
    """Empty/missing daily_blocks gets the three default meal entries."""
    from api.services.defaults import with_meal_defaults, DEFAULT_MEAL_BLOCKS

    # Missing entirely
    out = with_meal_defaults({"user": {"timezone": "America/Vancouver"}})
    assert out["daily_blocks"] == DEFAULT_MEAL_BLOCKS
    names = [b["name"] for b in out["daily_blocks"]]
    assert names == ["Breakfast", "Lunch", "Dinner"]


# ── Item 5: deadline reaches the LLM ─────────────────────────────────────────


def test_build_prompt_includes_task_deadline():
    """Tasks with a Todoist deadline must surface in the prompt — the LLM has
    no way to prioritise time-sensitive work otherwise."""
    from api.services.schedule_service import _build_prompt

    task = TodoistTask(
        id="t1", content="Finish proposal", project_id="p", priority=2,
        due_datetime=None, deadline="2026-04-15", duration_minutes=60,
        labels=[], is_inbox=False, is_rhythm=False,
    )
    prompt = _build_prompt([task], _make_windows(), _make_config(), "", "2026-04-12")
    assert "due=2026-04-15" in prompt
    # Header advertises the column so the LLM doesn't ignore it
    assert "deadline" in prompt


def test_build_prompt_includes_48_hour_deadline_rule():
    """The prompt must instruct the LLM to upgrade tasks with a deadline
    within 48 hours, so a P3 task with a deadline tomorrow doesn't get
    pushed in favor of a P2 with no deadline."""
    from api.services.schedule_service import _build_prompt
    prompt = _build_prompt(_make_tasks(), _make_windows(), _make_config(), "", "2026-04-12")
    # The rule references 48 hours and the priority elevation
    assert "48 hours" in prompt
    assert "P1" in prompt


def test_build_prompt_includes_rhythm_precedence_rule():
    """The prompt must explicitly tell the LLM that rhythms outrank P3/P4
    one-off tasks competing for the same window. Without this rule, the LLM
    treats rhythms as just-another-task ranked by their numeric priority
    encoding, and admin work routinely displaces them — which was the
    2026-04-28 user-reported failure mode (three rhythms pushed even though
    a 240-min late-night window was free)."""
    from api.services.schedule_service import _build_prompt
    prompt = _build_prompt(_make_tasks(), _make_windows(), _make_config(), "", "2026-04-12")
    # The rule references rhythms specifically + the priority decision
    assert "[rhythm]" in prompt
    assert "PLACE THE RHYTHM" in prompt
    # And the displacement carve-out (P1/P2 can still bump a rhythm)
    assert "P1/P2" in prompt or "P1 or P2" in prompt


# ── Item 6: surface_todoist_auth_failure shared module ───────────────────────


def test_surface_todoist_auth_failure_translates_to_400():
    """A RuntimeError carrying 'Todoist API auth failed' becomes the
    structured 400 response the frontend renders as a reconnect banner."""
    from fastapi import HTTPException
    from api.services.todoist_token import surface_todoist_auth_failure

    with pytest.raises(HTTPException) as excinfo:
        surface_todoist_auth_failure(RuntimeError("Todoist API auth failed: 401"))
    assert excinfo.value.status_code == 400
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "todoist_reconnect_required"
    assert "Todoist" in detail["message"]


def test_surface_todoist_auth_failure_reraises_unrelated_error():
    """Unrelated RuntimeErrors flow through unchanged so they surface as a
    real 500 in the route layer (instead of being silently masked as a
    reconnect prompt)."""
    from api.services.todoist_token import surface_todoist_auth_failure

    err = RuntimeError("compute_free_windows blew up")
    with pytest.raises(RuntimeError) as excinfo:
        surface_todoist_auth_failure(err)
    assert excinfo.value is err
