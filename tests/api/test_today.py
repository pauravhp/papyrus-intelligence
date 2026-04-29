import os, json
from datetime import date
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


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


def _mock_schedule_log(sb, rows):
    """Configure supabase mock to return schedule_log rows."""
    chain = (
        sb.from_.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .eq.return_value
        .order.return_value
        .execute.return_value
    )
    chain.data = rows
    # Default the queue chain to empty so pre-existing tests don't trip on the new query
    sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = []


def _build_today_mock_with_unreviewed_dates(dates: list[str]) -> MagicMock:
    """Build a supabase MagicMock configured for both schedule_log queries and the review_queue query."""
    mock_sb = MagicMock()
    # Main schedule_log query (yesterday/today/tomorrow) — return empty rows
    _mock_schedule_log(mock_sb, [])
    # Queue query chain: .eq(user_id).eq(confirmed).is_(reviewed_at).gte().lte().order().execute()
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = [
        {"schedule_date": d} for d in dates
    ]
    return mock_sb


def test_get_today_returns_three_days(client, monkeypatch):
    """GET /api/today returns yesterday/today/tomorrow keys."""
    from datetime import date, timedelta
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

    schedule = {
        "scheduled": [{"task_id": "1", "task_name": "Deep work", "start_time": f"{today_str}T09:00:00-07:00", "end_time": f"{today_str}T10:30:00-07:00", "duration_minutes": 90}],
        "pushed": [],
        "reasoning_summary": "Scheduled for focus time."
    }
    rows = [{"schedule_date": today_str, "proposed_json": json.dumps(schedule), "confirmed_at": f"{today_str}T08:00:00Z", "gcal_event_ids": "[]"}]

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, rows)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_svc = MagicMock()
    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(mock_svc, None)), \
         patch("api.routes.today.get_events", return_value=[]), \
         patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today.reconcile_today"), \
         patch("api.routes.today.get_user_calendars",
               return_value=(mock_svc, ["primary"], "UTC", False)):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert "yesterday" in data
    assert "today" in data
    assert "tomorrow" in data
    assert data["today"]["schedule_date"] == today_str
    assert len(data["today"]["scheduled"]) == 1
    assert data["yesterday"] is None
    assert data["tomorrow"] is None
    assert data["today"]["gcal_events"] == []
    assert data["today"]["all_day_events"] == []


def test_get_today_handles_no_schedule(client, monkeypatch):
    """GET /api/today returns None for all days when no confirmed schedules."""
    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, [])

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_svc = MagicMock()
    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(mock_svc, None)), \
         patch("api.routes.today.get_events", return_value=[]), \
         patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today.reconcile_today"), \
         patch("api.routes.today.get_user_calendars",
               return_value=(mock_svc, ["primary"], "UTC", False)):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["yesterday"] is None
    assert data["today"] is None
    assert data["tomorrow"] is None


def test_today_response_includes_review_available_false_before_cutoff(client):
    """review_available is False when current time is before sleep_time - 2.5h."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {
            "user": {"timezone": "America/New_York", "sleep_time": "23:00"},
            "rules": {"hard": []},
        },
    }
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]
    # 18:00 UTC = 14:00 ET — before cutoff of 20:30 ET
    mock_now = datetime(2026, 4, 15, 18, 0, 0, tzinfo=timezone.utc)

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is False


def test_today_response_includes_review_available_true_after_cutoff(client):
    """review_available is True when current time is at or after sleep_time - 2.5h."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {
            "user": {"timezone": "America/New_York", "sleep_time": "23:00"},
            "rules": {"hard": []},
        },
    }
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]
    # 01:00 UTC next day = 21:00 ET — after cutoff of 20:30 ET
    mock_now = datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc)

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is True


def test_today_review_available_false_when_no_confirmed_schedule(client):
    """review_available is False even after cutoff if no confirmed schedule exists."""
    from unittest.mock import patch, MagicMock
    from datetime import datetime, timezone

    mock_sb = MagicMock()
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {"user": {"timezone": "America/New_York"}, "rules": {"hard": []}},
    }
    # No confirmed schedule
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    mock_now = datetime(2026, 4, 16, 1, 0, 0, tzinfo=timezone.utc)  # after cutoff

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today._get_now", return_value=mock_now), \
         patch("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"}):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    assert resp.json()["review_available"] is False


def test_today_includes_gcal_events_when_no_confirmed_schedule(client, monkeypatch):
    """When no confirmed schedule exists but GCal has events, the day is non-null with gcal_events."""
    from datetime import date, datetime, timezone
    from src.models import CalendarEvent

    today = date.today()
    mock_start = datetime(today.year, today.month, today.day, 9, 0, tzinfo=timezone.utc)
    mock_end = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
    ev1 = CalendarEvent(id="evt-1", summary="Team sync", start=mock_start, end=mock_end, color_id=None, is_all_day=False)
    ev2 = CalendarEvent(id="evt-2", summary="1:1", start=mock_start, end=mock_end, color_id=None, is_all_day=False)

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, [])

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_svc = MagicMock()
    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(mock_svc, None)), \
         patch("api.routes.today.get_events", return_value=[ev1, ev2]), \
         patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["today"] is not None
    assert len(data["today"]["gcal_events"]) == 2
    assert data["today"]["scheduled"] == []


def test_today_filters_papyrus_created_events(client, monkeypatch):
    """Events whose IDs are in schedule_log.gcal_event_ids are excluded from gcal_events."""
    from datetime import date, datetime, timezone
    from src.models import CalendarEvent

    today = date.today()
    today_str = today.isoformat()
    mock_start = datetime(today.year, today.month, today.day, 9, 0, tzinfo=timezone.utc)
    mock_end = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)

    schedule = {"scheduled": [], "pushed": []}
    rows = [{
        "schedule_date": today_str,
        "proposed_json": json.dumps(schedule),
        "confirmed_at": f"{today_str}T08:00:00Z",
        "gcal_event_ids": json.dumps(["evt-papyrus-1"]),
    }]

    ev_papyrus = CalendarEvent(id="evt-papyrus-1", summary="Papyrus Task", start=mock_start, end=mock_end, color_id=None, is_all_day=False)
    ev_other = CalendarEvent(id="evt-other", summary="External Meeting", start=mock_start, end=mock_end, color_id=None, is_all_day=False)

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, rows)

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_svc = MagicMock()
    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(mock_svc, None)), \
         patch("api.routes.today.get_events", return_value=[ev_papyrus, ev_other]), \
         patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    event_ids = [e["id"] for e in data["today"]["gcal_events"]]
    assert "evt-papyrus-1" not in event_ids
    assert "evt-other" in event_ids


def test_today_degrades_gracefully_without_gcal_credentials(client, monkeypatch):
    """No GCal credentials → gcal_events: [], confirmed schedule still returns normally."""
    from datetime import date
    today_str = date.today().isoformat()
    schedule = {
        "scheduled": [{"task_id": "t1", "task_name": "Focus", "start_time": f"{today_str}T09:00:00Z", "end_time": f"{today_str}T10:00:00Z", "duration_minutes": 60}],
        "pushed": [],
    }
    rows = [{
        "schedule_date": today_str,
        "proposed_json": json.dumps(schedule),
        "confirmed_at": f"{today_str}T08:00:00Z",
        "gcal_event_ids": "[]",
    }]

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, rows)
    mock_sb.from_.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "config": {"user": {"timezone": "UTC"}, "calendar_ids": []},
        "google_credentials": None,
    }

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    with patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today.reconcile_today"), \
         patch("api.routes.today.get_user_calendars",
               return_value=(None, [], "UTC", False)):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["today"] is not None
    assert data["today"]["gcal_events"] == []
    assert len(data["today"]["scheduled"]) == 1


def test_today_separates_all_day_events(client, monkeypatch):
    """All-day events go to all_day_events, timed events go to gcal_events."""
    from datetime import date, datetime, timezone
    from src.models import CalendarEvent

    today = date.today()
    mock_start = datetime(today.year, today.month, today.day, 0, 0, tzinfo=timezone.utc)
    mock_end = datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc)
    timed_start = datetime(today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
    timed_end = datetime(today.year, today.month, today.day, 11, 0, tzinfo=timezone.utc)

    ev_all_day = CalendarEvent(id="evt-ad", summary="Holiday", start=mock_start, end=mock_end, color_id=None, is_all_day=True)
    ev_timed = CalendarEvent(id="evt-timed", summary="Meeting", start=timed_start, end=timed_end, color_id=None, is_all_day=False)

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, [])

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})

    mock_svc = MagicMock()
    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(mock_svc, None)), \
         patch("api.routes.today.get_events", return_value=[ev_all_day, ev_timed]), \
         patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["today"] is not None
    assert data["today"]["all_day_events"] == ["Holiday"]
    assert len(data["today"]["gcal_events"]) == 1
    assert data["today"]["gcal_events"][0]["summary"] == "Meeting"


def test_today_response_includes_empty_review_queue(client, monkeypatch):
    """review_queue has has_unreviewed=False and empty dates when no unreviewed rows exist."""
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mock_sb = _build_today_mock_with_unreviewed_dates([])
    with patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})
    assert resp.status_code == 200
    q = resp.json()["review_queue"]
    assert q == {"has_unreviewed": False, "count": 0, "dates": []}


def test_today_response_includes_unreviewed_dates_oldest_first(client, monkeypatch):
    """review_queue.dates are sorted oldest-first and count matches."""
    from datetime import date, timedelta
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "user-uuid-123"})
    mon = (date.today() - timedelta(days=2)).isoformat()
    wed = (date.today() - timedelta(days=1)).isoformat()
    mock_sb = _build_today_mock_with_unreviewed_dates([wed, mon])  # unsorted input
    with patch("api.routes.today.supabase", mock_sb):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake-jwt"})
    q = resp.json()["review_queue"]
    assert q["dates"] == sorted([mon, wed])
    assert q["count"] == 2
    assert q["has_unreviewed"] is True


def test_get_today_tags_kind_rhythm_vs_task(client, monkeypatch):
    """Items whose task_id starts with 'proj_' are rhythms; others are tasks."""
    rows = [{
        "schedule_date": date.today().isoformat(),
        "proposed_json": json.dumps({
            "scheduled": [
                {"task_id": "8675309", "task_name": "Write spec", "start_time": "2026-04-28T09:00:00-07:00", "end_time": "2026-04-28T10:30:00-07:00", "duration_minutes": 90, "category": "deep_work"},
                {"task_id": "proj_e1234567-89ab-cdef-0123-456789abcdef", "task_name": "Gym", "start_time": "2026-04-28T07:00:00-07:00", "end_time": "2026-04-28T07:45:00-07:00", "duration_minutes": 45, "category": None},
            ],
            "pushed": [],
        }),
        "confirmed_at": "2026-04-28T08:30:00-07:00",
        "gcal_event_ids": [],
    }]
    mock_sb = _build_today_mock_with_unreviewed_dates([])
    _mock_schedule_log(mock_sb, rows)
    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "u1"})
    monkeypatch.setattr("api.routes.today._fetch_day_gcal_events", lambda *a, **kw: ([], []))
    monkeypatch.setattr("api.routes.today.get_user_calendars", lambda *a, **kw: (None, [], "UTC", False))
    monkeypatch.setattr("api.routes.today.reconcile_today", lambda *a, **kw: None)

    with patch("api.routes.today.supabase", mock_sb):
        response = client.get("/api/today", headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    today = response.json().get("today")
    assert today is not None
    by_id = {item["task_id"]: item for item in today["scheduled"]}
    assert by_id["8675309"]["kind"] == "task"
    assert by_id["proj_e1234567-89ab-cdef-0123-456789abcdef"]["kind"] == "rhythm"


def test_today_calls_reconcile_and_hides_gcal_deleted(client, monkeypatch):
    """GET /api/today calls reconcile_today, surfaces todoist_completed_ids,
    and hides gcal_deleted items from response.today.scheduled."""
    today_str = date.today().isoformat()
    schedule = {
        "scheduled": [
            {"task_id": "t_keep",   "task_name": "Keep",   "start_time": f"{today_str}T09:00:00+00:00",
             "end_time": f"{today_str}T10:00:00+00:00", "duration_minutes": 60},
            {"task_id": "t_hidden", "task_name": "Hidden", "start_time": f"{today_str}T11:00:00+00:00",
             "end_time": f"{today_str}T12:00:00+00:00", "duration_minutes": 60, "gcal_deleted": True},
        ]
    }
    rows = [{
        "schedule_date": today_str,
        "proposed_json": json.dumps(schedule),
        "confirmed_at": f"{today_str}T08:00:00Z",
        "gcal_event_ids": json.dumps(["evt_keep", "evt_hidden"]),
    }]

    mock_sb = MagicMock()
    _mock_schedule_log(mock_sb, rows)
    # Wire the refreshed row re-read after reconcile (single-row chain with .eq().eq().eq().order().limit().execute())
    mock_sb.from_.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = rows

    monkeypatch.setattr("api.auth.verify_token", lambda token: {"sub": "u1"})

    from api.services.reconcile_service import ReconcileDelta
    fake_recon = MagicMock(return_value=ReconcileDelta())

    fake_tc = MagicMock()
    fake_tc.get_tasks.return_value = [MagicMock(id="t_keep")]
    fake_tc.get_completed_task_ids_for_date.return_value = {"t_done"}

    with patch("api.routes.today.build_gcal_service_from_credentials", return_value=(MagicMock(), None)), \
         patch("api.routes.today.get_events", return_value=[]), \
         patch("api.routes.today.supabase", mock_sb), \
         patch("api.routes.today.get_user_calendars",
               return_value=(MagicMock(), ["primary"], "UTC", True)), \
         patch("api.routes.today.reconcile_today", fake_recon), \
         patch("api.routes.today.TodoistClient", return_value=fake_tc), \
         patch("api.routes.today.get_valid_todoist_token", return_value="tok"):
        resp = client.get("/api/today", headers={"Authorization": "Bearer fake"})

    assert resp.status_code == 200
    body = resp.json()

    # reconcile_today was called with route="today" and the right Todoist sets
    assert fake_recon.called
    user_ctx = fake_recon.call_args[0][0]
    assert user_ctx["route"] == "today"
    assert user_ctx["todoist_active_ids"] == {"t_keep"}
    assert user_ctx["todoist_completed_ids"] == {"t_done"}

    # Today response excludes gcal_deleted items
    today_block = body["today"]
    task_ids = [s["task_id"] for s in today_block["scheduled"]]
    assert "t_keep" in task_ids
    assert "t_hidden" not in task_ids

    # Response surfaces completed IDs to frontend
    assert body["todoist_completed_ids"] == ["t_done"]
