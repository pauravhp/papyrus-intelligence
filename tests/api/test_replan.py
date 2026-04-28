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
import pytest
from fastapi.testclient import TestClient
from datetime import date, datetime, time

from api.services.extractor import ExtractionResult


def _empty_extraction():
    return ExtractionResult(blocks=[], cutoff_override_iso=None)


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _today():
    return date.today().isoformat()


def _mock_user_row(sb, config=None, todoist_token="tok-abc", gcal_creds=None):
    """Mock supabase users row lookup."""
    row = {
        "config": config or {"user": {"timezone": "America/Vancouver"}, "rules": {"hard": []}},
        "todoist_oauth_token": {"access_token": todoist_token},
        "google_credentials": gcal_creds,
    }
    (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ).data = row


def _mock_schedule_log_today(sb, scheduled=None, gcal_event_ids="[]"):
    """Mock the schedule_log query that loads today's confirmed schedule."""
    schedule = {
        "scheduled": scheduled or [
            {
                "task_id": "t1",
                "task_name": "Deep work",
                "start_time": f"{_today()}T13:00:00-07:00",
                "end_time": f"{_today()}T14:30:00-07:00",
                "duration_minutes": 90,
            }
        ],
        "pushed": [],
        "reasoning_summary": "Focus block in the afternoon.",
    }
    row = {
        "id": 1,
        "proposed_json": json.dumps(schedule),
        "gcal_event_ids": gcal_event_ids,
        "schedule_date": _today(),
        "confirmed_at": f"{_today()}T08:00:00Z",
    }
    return row, schedule


def test_replan_returns_proposed_schedule(client, monkeypatch):
    """POST /api/replan returns a proposed schedule without writing to GCal/Todoist."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    row, _ = _mock_schedule_log_today(mock_sb)

    # schedule_log lookup returns today's confirmed row
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_schedule_result = {
        "scheduled": [
            {
                "task_id": "t1",
                "task_name": "Deep work",
                "start_time": f"{_today()}T14:00:00-07:00",
                "end_time": f"{_today()}T15:30:00-07:00",
                "duration_minutes": 90,
            }
        ],
        "pushed": [],
        "reasoning_summary": "Shifted deep work by an hour.",
    }

    mock_now = datetime(_today_dt().year, _today_dt().month, _today_dt().day, 14, 0, 0)

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.replan._get_now", return_value=mock_now), \
         patch("api.services.planner.TodoistClient") as MockPlannerTodoist, \
         patch("api.services.planner.get_events", return_value=[]), \
         patch("api.services.planner.compute_free_windows", return_value=[]), \
         patch("api.services.planner.get_active_rhythms", return_value=[]), \
         patch("api.services.planner.extract_constraints", return_value=_empty_extraction()), \
         patch("api.services.planner.schedule_day", return_value=mock_schedule_result):

        MockTodoist.return_value.is_task_completed.return_value = False
        MockPlannerTodoist.return_value.get_tasks.return_value = []
        MockPlannerTodoist.return_value.get_todays_scheduled_tasks.return_value = []

        resp = client.post(
            "/api/replan",
            json={
                "task_states": {"t1": "keep"},
                "context_note": "running behind",
                "refinement_message": None,
            },
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "scheduled" in data
    assert "pushed" in data
    assert "reasoning_summary" in data


def test_replan_delegates_to_planner_pipeline(client, monkeypatch):
    """/api/replan delegates to planner.replan(), which runs the unified pipeline."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb)
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    today = date.today()
    mock_now = datetime(today.year, today.month, today.day, 14, 0, 0)

    captured = {}
    def fake_replan(**kwargs):
        captured["kwargs"] = kwargs
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok",
                "blocks": [], "cutoff_override": None, "free_windows_used": []}

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.replan._get_now", return_value=mock_now), \
         patch("api.services.planner.replan", side_effect=fake_replan):

        MockTodoist.return_value.is_task_completed.return_value = False
        MockTodoist.return_value.get_tasks.return_value = []

        resp = client.post(
            "/api/replan",
            json={"task_states": {"t1": "keep"}, "context_note": "context", "refinement_message": "refine me"},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    kw = captured["kwargs"]
    assert kw["target_date"] == today
    assert kw["candidate_tasks"] is not None  # route built keep + backlog
    # Mid-day current-time note + refinement + context all show up in prose
    assert "It is currently" in kw["prose"]
    assert "refine me" in kw["prose"]
    assert "context" in kw["prose"]


def test_replan_keep_task_project_id_is_string(client, monkeypatch):
    """Kept-from-today tasks must respect TodoistTask.project_id: str (not None).
    The model's annotation is non-Optional and downstream code in sync_engine
    + the sqlite writes treat project_id as a string. Passing None is a type
    lie that only doesn't crash because dataclasses don't runtime-check."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    # Schedule one task at 15:00 — after mock_now=14:00, so it WILL be in
    # afternoon_tasks_raw and the keep-task constructor runs. Other tests in
    # this file accidentally use 13:00 (before mock_now) which makes the
    # afternoon-filter exclude everything — keep_tasks ends up empty and any
    # type-check passes vacuously.
    today = date.today()
    scheduled_item = {
        "task_id": "t1",
        "task_name": "Deep work",
        "start_time": f"{today.isoformat()}T15:00:00-07:00",
        "end_time":   f"{today.isoformat()}T16:30:00-07:00",
        "duration_minutes": 90,
    }
    row, _ = _mock_schedule_log_today(mock_sb, scheduled=[scheduled_item])
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_now = datetime(today.year, today.month, today.day, 14, 0, 0)

    captured = {}
    def fake_replan(**kwargs):
        captured["candidate_tasks"] = kwargs.get("candidate_tasks") or []
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok",
                "blocks": [], "cutoff_override": None, "free_windows_used": []}

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.replan._get_now", return_value=mock_now), \
         patch("api.services.planner.replan", side_effect=fake_replan):

        MockTodoist.return_value.is_task_completed.return_value = False
        MockTodoist.return_value.get_tasks.return_value = []  # no backlog noise

        resp = client.post(
            "/api/replan",
            json={"task_states": {"t1": "keep"}, "context_note": "", "refinement_message": None},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200, resp.text
    candidates = captured["candidate_tasks"]
    # Sanity: the kept task actually made it through (otherwise the test is vacuous)
    kept = [t for t in candidates if t.id == "t1"]
    assert len(kept) == 1, f"kept task t1 missing from candidates: {[t.id for t in candidates]}"
    assert isinstance(kept[0].project_id, str), (
        f"keep task t1 has project_id={kept[0].project_id!r} — must be str per model annotation"
    )


def test_replan_disabled_before_noon(client, monkeypatch):
    """POST /api/replan returns 400 if called before noon."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    # Patch datetime.now() to return 11:00
    mock_now = datetime(_today_dt().year, _today_dt().month, _today_dt().day, 11, 0, 0)

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan._get_now", return_value=mock_now):
        resp = client.post(
            "/api/replan",
            json={"task_states": {}, "context_note": "", "refinement_message": None},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 400
    assert "before noon" in resp.json()["detail"].lower()


def test_replan_completed_tasks_auto_promoted(client, monkeypatch):
    """Tasks already completed in Todoist are auto-promoted to 'done' even if sent as 'keep'."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    row, _ = _mock_schedule_log_today(mock_sb)

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_schedule_result = {"scheduled": [], "pushed": [], "reasoning_summary": "Nothing to schedule."}
    mock_now = datetime(_today_dt().year, _today_dt().month, _today_dt().day, 14, 0, 0)

    captured_planner = {}
    def fake_replan(**kwargs):
        captured_planner["candidate_tasks"] = kwargs.get("candidate_tasks") or []
        return {"scheduled": [], "pushed": [], "reasoning_summary": "ok",
                "blocks": [], "cutoff_override": None, "free_windows_used": []}

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.replan._get_now", return_value=mock_now), \
         patch("api.services.planner.replan", side_effect=fake_replan):

        # Task is already completed in Todoist; route auto-promotes "keep" → "done"
        MockTodoist.return_value.is_task_completed.return_value = True
        MockTodoist.return_value.get_tasks.return_value = []  # no backlog

        resp = client.post(
            "/api/replan",
            json={
                "task_states": {"t1": "keep"},  # user sent "keep" but Todoist says done
                "context_note": "",
                "refinement_message": None,
            },
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    # The auto-promoted task should NOT be in the candidate_tasks passed to planner.
    candidate_ids = {t.id for t in captured_planner["candidate_tasks"]}
    assert "t1" not in candidate_ids


def _today_dt():
    return date.today()


# ── Todoist reconnect surface ─────────────────────────────────────────────────


def test_replan_returns_400_todoist_reconnect_required_when_helper_raises(client, monkeypatch):
    """When refresh fails, /api/replan must return 400 with the structured
    reconnect code so the frontend can prompt re-auth (not a generic toast)."""
    from api.services.todoist_token import TodoistTokenError

    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_now = datetime(_today_dt().year, _today_dt().month, _today_dt().day, 14, 0, 0)

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.get_valid_todoist_token",
               side_effect=TodoistTokenError("refresh rejected")), \
         patch("api.routes.replan._get_now", return_value=mock_now):
        resp = client.post(
            "/api/replan",
            json={"task_states": {}, "context_note": "", "refinement_message": ""},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "todoist_reconnect_required"


def test_replan_surfaces_runtime_auth_failure_as_reconnect_required(client, monkeypatch):
    """If Todoist 401s mid-call after our refresh check passed, the route
    must repackage RuntimeError('Todoist API auth failed') as the reconnect
    code rather than a generic 500."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)
    row, _ = _mock_schedule_log_today(mock_sb)
    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_now = datetime(_today_dt().year, _today_dt().month, _today_dt().day, 14, 0, 0)

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.get_valid_todoist_token", return_value="tok-abc"), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)), \
         patch("api.routes.replan._get_now", return_value=mock_now), \
         patch("api.services.planner.replan",
               side_effect=RuntimeError("Todoist API auth failed — check TODOIST_API_TOKEN")):
        MockTodoist.return_value.is_task_completed.return_value = False
        MockTodoist.return_value.get_tasks.return_value = []
        resp = client.post(
            "/api/replan",
            json={"task_states": {}, "context_note": "", "refinement_message": ""},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "todoist_reconnect_required"


def test_replan_confirm_deletes_afternoon_gcal_events(client, monkeypatch):
    """POST /api/replan/confirm deletes afternoon GCal events and creates new ones."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb, gcal_event_ids='["evt-1", "evt-2"]')

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 2}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_gcal = MagicMock()
    # Event 1 starts in the afternoon (should be deleted)
    mock_gcal.events.return_value.get.return_value.execute.return_value = {
        "start": {"dateTime": f"{_today()}T14:00:00-07:00"}
    }
    mock_gcal.events.return_value.delete.return_value.execute.return_value = {}
    mock_gcal.events.return_value.insert.return_value.execute.return_value = {"id": "new-evt-1"}

    schedule = {
        "scheduled": [
            {
                "task_id": "t1",
                "task_name": "Deep work",
                "start_time": f"{_today()}T15:00:00-07:00",
                "end_time": f"{_today()}T16:30:00-07:00",
                "duration_minutes": 90,
            }
        ],
        "pushed": [],
    }

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.routes.replan.delete_event") as mock_delete, \
         patch("api.routes.replan.create_event", return_value="new-evt-1"):

        MockTodoist.return_value.schedule_task.return_value = None

        resp = client.post(
            "/api/replan/confirm",
            json={"schedule": schedule, "tomorrow_task_ids": []},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["confirmed"] is True
    assert data["gcal_events_created"] == 1


def test_replan_confirm_pushes_tomorrow_tasks(client, monkeypatch):
    """POST /api/replan/confirm calls clear_task_due + add_comment for tomorrow_task_ids."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb)

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 2}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_gcal = MagicMock()

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.routes.replan.create_event", return_value="new-evt-1"):

        resp = client.post(
            "/api/replan/confirm",
            json={"schedule": {"scheduled": [], "pushed": []}, "tomorrow_task_ids": ["t2"]},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    MockTodoist.return_value.clear_task_due.assert_called_once_with("t2")
    MockTodoist.return_value.add_comment.assert_called_once()


def test_replan_preflight_returns_completed_ids(client, monkeypatch):
    """POST /api/replan/preflight returns task IDs that Todoist marks as completed."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(MagicMock(), False)):

        def is_completed(task_id):
            return task_id == "t1"
        MockTodoist.return_value.is_task_completed.side_effect = is_completed

        resp = client.post(
            "/api/replan/preflight",
            json={"task_ids": ["t1", "t2"]},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["completed_ids"] == ["t1"]


def test_replan_confirm_fires_analytics(client, monkeypatch):
    from unittest.mock import patch
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb)

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 2}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_gcal = MagicMock()
    body = {
        "schedule": {"scheduled": [
            {"task_id": "t1", "task_name": "Deep work", "start_time": "2026-04-17T14:00:00",
             "end_time": "2026-04-17T15:30:00", "duration_minutes": 90}
        ], "pushed": []},
        "tomorrow_task_ids": [],
    }

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.routes.replan.capture") as mock_capture, \
         patch("api.routes.replan.create_event", return_value="gcal-id"):
        MockTodoist.return_value.schedule_task.return_value = None
        resp = client.post("/api/replan/confirm", json=body, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    mock_capture.assert_called_once()
    assert mock_capture.call_args[0][1] == "replan_confirmed"


def test_replan_confirm_deletes_from_correct_calendar(client, monkeypatch):
    """POST /api/replan/confirm deletes old events using gcal_write_calendar_id from the log row."""
    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb, gcal_event_ids='["old-evt-1"]')
    row["gcal_write_calendar_id"] = "work@co.com"  # was written to work calendar

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    (
        mock_sb.from_.return_value
        .insert.return_value
        .execute.return_value
    ).data = [{"id": 2}]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_gcal = MagicMock()
    # Mock events().get() to return a future event (so delete proceeds)
    from datetime import datetime, timedelta
    future_dt = (datetime.now() + timedelta(hours=2)).isoformat()
    mock_gcal.events.return_value.get.return_value.execute.return_value = {
        "start": {"dateTime": future_dt}
    }

    schedule = {
        "scheduled": [{
            "task_id": "t1",
            "task_name": "Deep work",
            "start_time": f"{_today()}T15:00:00-07:00",
            "end_time":   f"{_today()}T16:30:00-07:00",
            "duration_minutes": 90,
        }],
        "pushed": [],
    }

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.routes.replan.delete_event") as mock_delete, \
         patch("api.routes.replan.create_event", return_value="new-evt-1"):

        MockTodoist.return_value.schedule_task.return_value = None

        client.post(
            "/api/replan/confirm",
            json={"schedule": schedule, "tomorrow_task_ids": []},
            headers={"Authorization": "Bearer fake-jwt"},
        )

    # delete_event must be called with the calendar from the log row
    mock_delete.assert_called_once()
    _, kwargs = mock_delete.call_args
    assert kwargs.get("calendar_id") == "work@co.com"


# ── Double-confirm guard for replan (item #4) ─────────────────────────────────


def test_replan_confirm_idempotent_when_recently_confirmed(client, monkeypatch):
    """Second click on replan-confirm within window: no-op return, no GCal writes."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    mock_sb = MagicMock()
    _mock_user_row(mock_sb, gcal_creds={"token": "gcal-tok"})
    row, _ = _mock_schedule_log_today(mock_sb, gcal_event_ids='["evt-x", "evt-y"]')
    # Simulate a row that was just confirmed via replan, 2 seconds ago
    row["replan_trigger"] = "mid_day_replan"
    row["confirmed_at"] = (datetime.now(ZoneInfo("UTC")) - timedelta(seconds=2)).isoformat()
    row["id"] = 88

    (
        mock_sb.from_.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ).data = [row]

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    body = {
        "schedule": {"scheduled": [
            {"task_id": "t1", "task_name": "Deep work",
             "start_time": f"{_today()}T15:00:00-07:00",
             "end_time":   f"{_today()}T16:30:00-07:00",
             "duration_minutes": 90}
        ], "pushed": []},
        "tomorrow_task_ids": [],
    }

    mock_gcal = MagicMock()

    with patch("api.routes.replan.supabase", mock_sb), \
         patch("api.routes.replan.TodoistClient") as MockTodoist, \
         patch("api.routes.replan.build_gcal_service_from_credentials", return_value=(mock_gcal, False)), \
         patch("api.routes.replan.create_event") as mock_create, \
         patch("api.routes.replan.delete_event") as mock_delete:
        resp = client.post("/api/replan/confirm", json=body, headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["confirmed"] is True
    assert data.get("schedule_log_id") == 88
    # No new writes — full idempotent replay
    mock_create.assert_not_called()
    mock_delete.assert_not_called()
    MockTodoist.return_value.schedule_task.assert_not_called()
    mock_sb.from_.return_value.insert.assert_not_called()
