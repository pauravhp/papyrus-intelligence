"""
Tests for the unified scheduling pipeline via /api/plan, /api/refine, and
/api/plan/confirm.

Architecture under test:
  prose → extract_constraints (LLM) → blocks + cutoff_override
        → compute_free_windows (constraints baked in)
        → schedule_day (LLM) → scheduled + pushed + reasoning_summary
        → Python validators → final response
"""

import os, json
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-32-chars-padding!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-gcal-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-gcal-secret")
os.environ.setdefault("TODOIST_CLIENT_ID", "test-td-id")
os.environ.setdefault("TODOIST_CLIENT_SECRET", "test-td-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

from unittest.mock import MagicMock, patch
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from src.models import TodoistTask, FreeWindow
from api.services.extractor import Block, ExtractionResult


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _today():
    return date.today().isoformat()


def _mock_user_row(sb, config=None, gcal_creds=None):
    row = {
        "config": config or {
            "user": {"timezone": "America/Vancouver"},
            "rules": {"hard": []},
            "daily_blocks": [],
            "source_calendar_ids": ["primary"],
        },
        "todoist_oauth_token": {"access_token": "tok-abc"},
        "google_credentials": gcal_creds or {"token": "gcal-tok"},
    }
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = row


def _stub_task(tid, content="Stub", duration=60):
    return TodoistTask(
        id=tid, content=content, project_id="p", priority=3,
        due_datetime=None, deadline=None, duration_minutes=duration,
        labels=[], is_inbox=False, is_rhythm=False,
    )


def _stub_window():
    tz = ZoneInfo("America/Vancouver")
    today = date.today()
    return FreeWindow(
        start=datetime(today.year, today.month, today.day, 14, 0, tzinfo=tz),
        end=datetime(today.year, today.month, today.day, 18, 0, tzinfo=tz),
        duration_minutes=240,
        block_type="afternoon",
    )


def _patch_pipeline(*, sb, gcal=None, todoist_tasks=None, scheduled_tasks=None,
                    extraction=None, schedule_day_fn=None,
                    free_windows=None, get_events_result=None):
    """Apply the standard pipeline mock stack as a context manager stack of patches."""
    from contextlib import ExitStack
    stack = ExitStack()
    mock_gcal = gcal or MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = todoist_tasks or []
    mock_todoist.get_todays_scheduled_tasks.return_value = scheduled_tasks or []

    extracted = extraction if extraction is not None else ExtractionResult(blocks=[], cutoff_override_iso=None)

    def default_schedule_day(**_kwargs):
        return {"scheduled": [], "pushed": [], "reasoning_summary": ""}

    schedule_fn = schedule_day_fn or default_schedule_day

    stack.enter_context(patch("api.routes.plan.supabase", sb))
    stack.enter_context(patch("api.routes.plan.build_gcal_service_from_credentials",
                              return_value=(mock_gcal, False)))
    stack.enter_context(patch("api.services.planner.TodoistClient", return_value=mock_todoist))
    stack.enter_context(patch("api.services.planner.get_events",
                              return_value=get_events_result or []))
    stack.enter_context(patch("api.services.planner.compute_free_windows",
                              return_value=free_windows if free_windows is not None else [_stub_window()]))
    stack.enter_context(patch("api.services.planner.get_active_rhythms", return_value=[]))
    stack.enter_context(patch("api.services.planner.extract_constraints", return_value=extracted))
    stack.enter_context(patch("api.services.planner.schedule_day", side_effect=schedule_fn))
    return stack, mock_gcal, mock_todoist


# ── /api/plan ─────────────────────────────────────────────────────────────────


def test_plan_runs_extract_then_schedule(client, monkeypatch):
    """Pipeline: one extract call, then one schedule call. Both invoked."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    captured = {"schedule_calls": 0}
    def fake_schedule_day(**kwargs):
        captured["schedule_calls"] += 1
        captured["last_kwargs"] = kwargs
        return {
            "scheduled": [{
                "task_id": "t1", "task_name": "Do focused work",
                "start_time": f"{_today()}T14:00:00-07:00",
                "end_time": f"{_today()}T15:30:00-07:00",
                "duration_minutes": 90, "category": "deep_work",
            }],
            "pushed": [],
            "reasoning_summary": "Focused work in your afternoon window.",
        }

    stack, _, _ = _patch_pipeline(
        sb=mock_sb,
        todoist_tasks=[_stub_task("t1", "Do focused work", 90)],
        schedule_day_fn=fake_schedule_day,
    )

    with stack:
        resp = client.post(
            "/api/plan",
            json={"target_date": "today", "context_note": "light day"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scheduled"][0]["task_id"] == "t1"
    assert captured["schedule_calls"] == 1
    sd = captured["last_kwargs"]
    assert "USER NOTE: light day" in sd["context_note"]
    assert sd["target_date"] == _today()
    # Plan response surfaces blocks + cutoff_override (empty here, but field present)
    assert "blocks" in data and data["blocks"] == []
    assert data["cutoff_override"] is None


def test_extracted_block_excludes_time_from_windows(client, monkeypatch):
    """When extractor returns a block, the synthesized event reaches compute_free_windows."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    extraction = ExtractionResult(
        blocks=[Block(
            start_iso=f"{_today()}T16:00:00-07:00",
            end_iso=f"{_today()}T21:00:00-07:00",
            source="event 4-9pm",
        )],
        cutoff_override_iso=None,
    )

    captured = {}
    def fake_compute_free_windows(events, target_date, config, scheduled_tasks=None, **_kw):
        captured["events"] = events
        return [_stub_window()]

    def fake_schedule_day(**_kwargs):
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok"}

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", side_effect=fake_compute_free_windows), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints", return_value=extraction), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/plan",
            json={"target_date": "today", "context_note": "I have an event 4-9pm"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    block = next((e for e in captured["events"] if "user_block_" in getattr(e, "id", "")), None)
    assert block is not None
    assert (block.start.hour, block.end.hour) == (16, 21)


def test_cutoff_override_extends_no_tasks_after(client, monkeypatch):
    """When extractor sets a post-midnight cutoff, the config passed to compute_free_windows reflects it."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, config={
        "user": {"timezone": "America/Vancouver"},
        "rules": {"hard": []},
        "daily_blocks": [],
        "source_calendar_ids": ["primary"],
        "sleep": {"no_tasks_after": "23:00"},
    })
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    extraction = ExtractionResult(
        blocks=[],
        cutoff_override_iso=f"{tomorrow}T03:30:00-07:00",
    )

    captured = {}
    def fake_compute_free_windows(events, target_date, config, scheduled_tasks=None, **_kw):
        captured["no_tasks_after"] = config.get("sleep", {}).get("no_tasks_after")
        return [_stub_window()]

    def fake_schedule_day(**_kwargs):
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok"}

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", side_effect=fake_compute_free_windows), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints", return_value=extraction), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/plan",
            json={"target_date": "today", "context_note": "I can work till 3:30am"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    # cutoff is on next day → "next day" suffix
    assert captured["no_tasks_after"] == "03:30 next day"
    assert resp.json()["cutoff_override"] == f"{tomorrow}T03:30:00-07:00"


# ── /api/refine ───────────────────────────────────────────────────────────────


def test_refine_carries_blocks_into_extractor(client, monkeypatch):
    """previous_proposal.blocks reach the extractor as previous_blocks for carry-forward."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    captured = {}
    def fake_extract(**kwargs):
        captured["previous_blocks"] = kwargs.get("previous_blocks")
        captured["previous_cutoff"] = kwargs.get("previous_cutoff_iso")
        captured["prose"] = kwargs.get("prose")
        # Echo the previous block forward
        return ExtractionResult(blocks=list(kwargs.get("previous_blocks") or []),
                                cutoff_override_iso=kwargs.get("previous_cutoff_iso"))

    def fake_schedule_day(**_kwargs):
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok"}

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = []
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    previous_proposal = {
        "scheduled": [],
        "pushed": [],
        "blocks": [
            {"start_iso": f"{_today()}T22:00:00-07:00",
             "end_iso":   f"{(date.today() + timedelta(days=1)).isoformat()}T00:30:00-07:00",
             "source": "event 10pm-12:30am"},
        ],
        "cutoff_override": None,
    }

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", return_value=[_stub_window()]), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints", side_effect=fake_extract), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/refine",
            json={
                "target_date": "today",
                "previous_proposal": previous_proposal,
                "refinement_message": "actually do Todoist Scheduler for the entirety of today",
                "original_context_note": "",
            },
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    # Carry-forward arrived at the extractor
    assert len(captured["previous_blocks"]) == 1
    assert captured["previous_blocks"][0].source == "event 10pm-12:30am"
    # The new prose is included for the extractor to consider
    assert "Todoist Scheduler" in captured["prose"]
    # Response carries the block forward
    blocks = resp.json()["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["source"] == "event 10pm-12:30am"


# ── Validators ────────────────────────────────────────────────────────────────


def test_validator_rejects_block_overlapping_item(client, monkeypatch):
    """LLM placed an item in time the extractor declared blocked → moved to pushed."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    today_iso = _today()
    extraction = ExtractionResult(
        blocks=[Block(
            start_iso=f"{today_iso}T16:00:00-07:00",
            end_iso=f"{today_iso}T21:00:00-07:00",
            source="event 4-9pm",
        )],
        cutoff_override_iso=None,
    )

    def fake_schedule_day(**_kwargs):
        return {
            "scheduled": [
                {"task_id": "ok", "task_name": "OK", "duration_minutes": 30,
                 "start_time": f"{today_iso}T14:00:00-07:00",
                 "end_time":   f"{today_iso}T14:30:00-07:00"},
                {"task_id": "violator", "task_name": "Violator", "duration_minutes": 60,
                 "start_time": f"{today_iso}T17:00:00-07:00",  # inside 16-21 block
                 "end_time":   f"{today_iso}T18:00:00-07:00"},
            ],
            "pushed": [],
            "reasoning_summary": "ok",
        }

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = [
        _stub_task("ok", "OK", 30),
        _stub_task("violator", "Violator", 60),
    ]
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", return_value=[_stub_window()]), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints", return_value=extraction), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/refine",
            json={
                "target_date": "today",
                "previous_proposal": {"scheduled": [], "pushed": [], "blocks": [], "cutoff_override": None},
                "refinement_message": "I have an event 4-9pm",
            },
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    kept_ids = {i["task_id"] for i in data["scheduled"]}
    pushed_ids = {i["task_id"] for i in data["pushed"]}
    assert kept_ids == {"ok"}
    assert "violator" in pushed_ids
    violator = next(p for p in data["pushed"] if p["task_id"] == "violator")
    assert "blocked" in violator["reason"].lower()


def test_validator_rejects_truncated_task(client, monkeypatch):
    """LLM emitted duration_minutes far below the original → rejected as truncation."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    today_iso = _today()

    def fake_schedule_day(**_kwargs):
        # Original task is 90m; LLM emits 30m → truncation.
        return {
            "scheduled": [{
                "task_id": "shrunk", "task_name": "Big Task", "duration_minutes": 30,
                "start_time": f"{today_iso}T14:00:00-07:00",
                "end_time":   f"{today_iso}T14:30:00-07:00",
            }],
            "pushed": [],
            "reasoning_summary": "ok",
        }

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = [_stub_task("shrunk", "Big Task", 90)]
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", return_value=[_stub_window()]), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints",
               return_value=ExtractionResult(blocks=[], cutoff_override_iso=None)), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/plan",
            json={"target_date": "today", "context_note": ""},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scheduled"] == []
    assert len(data["pushed"]) == 1
    assert data["pushed"][0]["task_id"] == "shrunk"
    assert "duration" in data["pushed"][0]["reason"].lower() or "fit" in data["pushed"][0]["reason"].lower()


def test_validator_accepts_legitimate_split(client, monkeypatch):
    """A 180m task split into 100m + 80m (sums to 180) passes truncation check."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    today_iso = _today()

    def fake_schedule_day(**_kwargs):
        return {
            "scheduled": [
                {"task_id": "split", "task_name": "Big (pt 1)", "duration_minutes": 100,
                 "start_time": f"{today_iso}T14:00:00-07:00",
                 "end_time":   f"{today_iso}T15:40:00-07:00"},
                {"task_id": "split", "task_name": "Big (pt 2)", "duration_minutes": 80,
                 "start_time": f"{today_iso}T16:00:00-07:00",
                 "end_time":   f"{today_iso}T17:20:00-07:00"},
            ],
            "pushed": [],
            "reasoning_summary": "split across two windows",
        }

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()
    mock_todoist.get_tasks.return_value = [_stub_task("split", "Big", 180)]
    mock_todoist.get_todays_scheduled_tasks.return_value = []

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", return_value=[_stub_window()]), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints",
               return_value=ExtractionResult(blocks=[], cutoff_override_iso=None)), \
         patch("api.services.planner.schedule_day", side_effect=fake_schedule_day):

        resp = client.post(
            "/api/plan",
            json={"target_date": "today", "context_note": ""},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["scheduled"]) == 2
    assert data["pushed"] == []


# ── /api/plan/confirm ─────────────────────────────────────────────────────────


def test_confirm_writes_gcal_and_todoist_and_logs(client, monkeypatch):
    """POST /api/plan/confirm persists schedule with NO LLM calls."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    # Idempotency-guard SELECT returns no existing confirmed row
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = []

    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 42}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    schedule = {
        "scheduled": [
            {
                "task_id": "t1", "task_name": "Real task",
                "start_time": f"{_today()}T14:00:00-07:00",
                "end_time": f"{_today()}T15:00:00-07:00",
                "duration_minutes": 60,
            },
            {
                "task_id": "proj_99", "task_name": "Rhythm task",
                "start_time": f"{_today()}T15:00:00-07:00",
                "end_time": f"{_today()}T16:00:00-07:00",
                "duration_minutes": 60,
            },
        ],
        "pushed": [],
    }

    mock_gcal = MagicMock()
    mock_todoist = MagicMock()

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.services.planner.TodoistClient", return_value=mock_todoist), \
         patch("api.services.planner.create_event", return_value="gcal-id-1") as mock_create, \
         patch("api.services.planner.schedule_day") as fake_schedule_day, \
         patch("api.services.planner.extract_constraints") as fake_extract:

        resp = client.post(
            "/api/plan/confirm",
            json={"target_date": "today", "schedule": schedule},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["confirmed"] is True
    assert data["gcal_events_created"] == 2
    assert data["todoist_updated"] == 1  # proj_99 is rhythm — skipped
    assert data["schedule_log_id"] == 42
    fake_schedule_day.assert_not_called()
    fake_extract.assert_not_called()
    assert mock_create.call_count == 2
    mock_todoist.schedule_task.assert_called_once()
    args, _ = mock_todoist.schedule_task.call_args
    assert args[0] == "t1"


# ── Double-confirm guard (item #4) ────────────────────────────────────────────


def _setup_existing_confirmed_row(mock_sb, *, confirmed_at_iso, replan_trigger=None,
                                   row_id=99, gcal_event_ids='["old-1", "old-2"]'):
    """Mock the schedule_log SELECT used by planner.confirm's idempotency guard."""
    existing_row = {
        "id": row_id,
        "confirmed_at": confirmed_at_iso,
        "gcal_event_ids": gcal_event_ids,
        "replan_trigger": replan_trigger,
    }
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [existing_row]


def test_confirm_rejects_when_older_confirmed_row_exists(client, monkeypatch):
    """If today is already confirmed (older than the idempotency window), 409."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    # Confirmed 5 minutes ago — well outside the 30s window
    five_min_ago = (datetime.now(ZoneInfo("UTC")) - timedelta(minutes=5)).isoformat()
    _setup_existing_confirmed_row(mock_sb, confirmed_at_iso=five_min_ago)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    schedule = {"scheduled": [], "pushed": []}

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.services.planner.TodoistClient"), \
         patch("api.services.planner.create_event") as mock_create:

        resp = client.post(
            "/api/plan/confirm",
            json={"target_date": "today", "schedule": schedule},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 409, resp.text
    assert "already confirmed" in resp.json()["detail"].lower()
    mock_create.assert_not_called()
    mock_sb.from_.return_value.insert.assert_not_called()


def test_confirm_returns_idempotent_when_recently_confirmed(client, monkeypatch):
    """Double-click on plan/confirm: existing recent row → return its id, no writes."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    # Confirmed 2 seconds ago — well inside the window
    two_sec_ago = (datetime.now(ZoneInfo("UTC")) - timedelta(seconds=2)).isoformat()
    _setup_existing_confirmed_row(
        mock_sb, confirmed_at_iso=two_sec_ago, row_id=77,
        gcal_event_ids='["evt-a", "evt-b"]',
    )

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    schedule = {
        "scheduled": [
            {"task_id": "t1", "task_name": "X",
             "start_time": f"{_today()}T14:00:00-07:00",
             "end_time": f"{_today()}T15:00:00-07:00",
             "duration_minutes": 60},
        ],
        "pushed": [],
    }

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.services.planner.TodoistClient"), \
         patch("api.services.planner.create_event") as mock_create:

        resp = client.post(
            "/api/plan/confirm",
            json={"target_date": "today", "schedule": schedule},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["confirmed"] is True
    assert data["schedule_log_id"] == 77
    # No new GCal events created, no new schedule_log row inserted
    mock_create.assert_not_called()
    mock_sb.from_.return_value.insert.assert_not_called()


def test_confirm_proceeds_when_no_existing_row(client, monkeypatch):
    """No prior confirm today → normal write path runs."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    # SELECT returns empty list → no existing confirmed row
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = []
    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 100}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    schedule = {
        "scheduled": [
            {"task_id": "t1", "task_name": "X",
             "start_time": f"{_today()}T14:00:00-07:00",
             "end_time": f"{_today()}T15:00:00-07:00",
             "duration_minutes": 60},
        ],
        "pushed": [],
    }

    with patch("api.routes.plan.supabase", mock_sb), \
         patch("api.routes.plan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.services.planner.TodoistClient"), \
         patch("api.services.planner.create_event", return_value="new-evt-1") as mock_create:

        resp = client.post(
            "/api/plan/confirm",
            json={"target_date": "today", "schedule": schedule},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule_log_id"] == 100
    assert mock_create.call_count == 1
