"""Unit tests for api.services.reconcile_service."""

from api.services.reconcile_service import (
    ReconcileDelta,
    TaskMove,
    TaskEdit,
    DropReason,
)


def test_reconcile_delta_constructs_empty():
    delta = ReconcileDelta(
        moved=[],
        edited=[],
        gcal_deleted=[],
        dropped=[],
        skipped_reviewed=False,
    )
    assert delta.moved == []
    assert delta.skipped_reviewed is False


def test_task_move_holds_old_and_new_times():
    m = TaskMove(
        task_id="t1",
        old_start="2026-04-29T09:00:00-07:00",
        new_start="2026-04-29T16:00:00-07:00",
        old_end="2026-04-29T10:00:00-07:00",
        new_end="2026-04-29T17:00:00-07:00",
    )
    assert m.task_id == "t1"
    assert m.old_start != m.new_start


def test_task_edit_field_must_be_title_or_duration():
    e = TaskEdit(task_id="t1", field="title", old_value="A", new_value="B")
    assert e.field == "title"
    e2 = TaskEdit(task_id="t1", field="duration", old_value=60, new_value=30)
    assert e2.field == "duration"


def test_drop_reason_carries_gcal_state():
    d = DropReason(task_id="t1", reason="todoist_deleted", gcal_state="missing")
    assert d.reason == "todoist_deleted"
    assert d.gcal_state == "missing"


from api.services.reconcile_service import GcalState, classify_gcal


def _gcal_event(event_id: str, summary: str, start: str, end: str) -> dict:
    return {
        "id": event_id,
        "summary": summary,
        "start_time": start,
        "end_time": end,
    }


def _scheduled_item(task_id: str, name: str, start: str, end: str, duration: int) -> dict:
    return {
        "task_id": task_id,
        "task_name": name,
        "start_time": start,
        "end_time": end,
        "duration_minutes": duration,
    }


def test_classify_gcal_missing_when_event_id_not_in_index():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    state = classify_gcal({}, "evt_missing", item)
    assert state.kind == "missing"


def test_classify_gcal_present_when_unchanged():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal = {"evt1": _gcal_event("evt1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00")}
    state = classify_gcal(gcal, "evt1", item)
    assert state.kind == "present"
    assert state.title_changed is False
    assert state.duration_changed is False


def test_classify_gcal_moved_when_instant_shifts():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal = {"evt1": _gcal_event("evt1", "X", "2026-04-29T16:00:00+00:00", "2026-04-29T17:00:00+00:00")}
    state = classify_gcal(gcal, "evt1", item)
    assert state.kind == "moved"
    assert state.new_start == "2026-04-29T16:00:00+00:00"
    assert state.new_end == "2026-04-29T17:00:00+00:00"


def test_classify_gcal_edited_title_only():
    item = _scheduled_item("t1", "Old", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal = {"evt1": _gcal_event("evt1", "New", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00")}
    state = classify_gcal(gcal, "evt1", item)
    assert state.kind == "edited"
    assert state.title_changed is True
    assert state.duration_changed is False
    assert state.new_title == "New"


def test_classify_gcal_edited_duration_only():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal = {"evt1": _gcal_event("evt1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T09:30:00+00:00")}
    state = classify_gcal(gcal, "evt1", item)
    assert state.kind == "edited"
    assert state.title_changed is False
    assert state.duration_changed is True
    assert state.new_duration_minutes == 30


def test_classify_gcal_moved_and_edited_co_occur():
    item = _scheduled_item("t1", "Old", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal = {"evt1": _gcal_event("evt1", "New", "2026-04-29T16:00:00+00:00", "2026-04-29T16:30:00+00:00")}
    state = classify_gcal(gcal, "evt1", item)
    assert state.kind == "moved"
    assert state.title_changed is True
    assert state.duration_changed is True
    assert state.new_title == "New"
    assert state.new_duration_minutes == 30


def test_classify_gcal_empty_event_id_is_missing():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    state = classify_gcal({"evt1": _gcal_event("evt1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00")}, "", item)
    assert state.kind == "missing"


from api.services.reconcile_service import TodoistState, classify_todoist


def test_classify_todoist_na_for_proj_task_id():
    item = {"task_id": "proj_42", "task_name": "Finish project"}
    state = classify_todoist(active_ids=set(), completed_ids=set(), item=item)
    assert state == TodoistState.NA


def test_classify_todoist_pending_when_in_active_set():
    item = {"task_id": "12345", "task_name": "X"}
    state = classify_todoist(active_ids={"12345"}, completed_ids=set(), item=item)
    assert state == TodoistState.PENDING


def test_classify_todoist_completed_when_in_completed_set():
    item = {"task_id": "12345", "task_name": "X"}
    state = classify_todoist(active_ids=set(), completed_ids={"12345"}, item=item)
    assert state == TodoistState.COMPLETED


def test_classify_todoist_completed_takes_precedence_over_active():
    """Edge case: race condition where Todoist reports task in both lists."""
    item = {"task_id": "12345"}
    state = classify_todoist(active_ids={"12345"}, completed_ids={"12345"}, item=item)
    assert state == TodoistState.COMPLETED


def test_classify_todoist_deleted_when_in_neither_set():
    item = {"task_id": "12345", "task_name": "X"}
    state = classify_todoist(active_ids=set(), completed_ids=set(), item=item)
    assert state == TodoistState.DELETED


from api.services.reconcile_service import _apply_rule


def _delta() -> ReconcileDelta:
    return ReconcileDelta()


def test_apply_rule_present_pending_is_noop():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="present")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.PENDING, delta)
    assert action == "KEEP"
    assert delta.has_writes() is False
    assert "gcal_deleted" not in item


def test_apply_rule_moved_pending_mutates_times_and_records():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(
        kind="moved",
        new_start="2026-04-29T16:00:00+00:00",
        new_end="2026-04-29T17:00:00+00:00",
    )
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.PENDING, delta)
    assert action == "KEEP"
    assert item["start_time"] == "2026-04-29T16:00:00+00:00"
    assert item["end_time"] == "2026-04-29T17:00:00+00:00"
    assert len(delta.moved) == 1
    assert delta.moved[0].task_id == "t1"
    assert delta.moved[0].old_start == "2026-04-29T09:00:00+00:00"
    assert delta.moved[0].new_start == "2026-04-29T16:00:00+00:00"


def test_apply_rule_moved_with_title_change_records_both():
    item = _scheduled_item("t1", "Old", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(
        kind="moved",
        title_changed=True,
        new_start="2026-04-29T16:00:00+00:00",
        new_end="2026-04-29T17:00:00+00:00",
        new_title="New",
    )
    delta = _delta()
    _apply_rule(item, gcal_state, TodoistState.PENDING, delta)
    assert item["task_name"] == "New"
    assert len(delta.moved) == 1
    assert len(delta.edited) == 1
    assert delta.edited[0].field == "title"


def test_apply_rule_edited_duration_pending_mutates_and_records():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="edited", duration_changed=True, new_duration_minutes=30)
    delta = _delta()
    _apply_rule(item, gcal_state, TodoistState.PENDING, delta)
    assert item["duration_minutes"] == 30
    assert len(delta.edited) == 1
    assert delta.edited[0].field == "duration"
    assert delta.edited[0].new_value == 30


def test_apply_rule_missing_pending_marks_gcal_deleted():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="missing")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.PENDING, delta)
    assert action == "KEEP"
    assert item["gcal_deleted"] is True
    assert "t1" in delta.gcal_deleted


def test_apply_rule_present_deleted_drops():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="present")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.DELETED, delta)
    assert action == "DROP"
    assert len(delta.dropped) == 1
    assert delta.dropped[0].task_id == "t1"
    assert delta.dropped[0].reason == "todoist_deleted"
    assert delta.dropped[0].gcal_state == "present"


def test_apply_rule_missing_deleted_drops_with_missing_gcal_state():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="missing")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.DELETED, delta)
    assert action == "DROP"
    assert delta.dropped[0].gcal_state == "missing"


def test_apply_rule_missing_completed_marks_gcal_deleted_not_drop():
    """Row 10: GCal deleted but Todoist still says completed — keep for Review."""
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="missing")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.COMPLETED, delta)
    assert action == "KEEP"
    assert item["gcal_deleted"] is True


def test_apply_rule_moved_completed_mutates_times_no_drop():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(
        kind="moved",
        new_start="2026-04-29T16:00:00+00:00",
        new_end="2026-04-29T17:00:00+00:00",
    )
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.COMPLETED, delta)
    assert action == "KEEP"
    assert item["start_time"] == "2026-04-29T16:00:00+00:00"


def test_apply_rule_proj_missing_marks_gcal_deleted():
    """proj_ tasks: no Todoist column applies, GCal-only rules."""
    item = _scheduled_item("proj_42", "Finish project", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="missing")
    delta = _delta()
    action = _apply_rule(item, gcal_state, TodoistState.NA, delta)
    assert action == "KEEP"
    assert item["gcal_deleted"] is True


def test_apply_rule_proj_moved_mutates():
    item = _scheduled_item("proj_42", "Finish project", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    gcal_state = GcalState(kind="moved", new_start="2026-04-29T16:00:00+00:00", new_end="2026-04-29T17:00:00+00:00")
    delta = _delta()
    _apply_rule(item, gcal_state, TodoistState.NA, delta)
    assert item["start_time"] == "2026-04-29T16:00:00+00:00"
    assert len(delta.moved) == 1


import json as _json
from datetime import date as _date
from unittest.mock import MagicMock

from api.services.reconcile_service import reconcile_today


def _mock_supabase_with_row(row: dict | None) -> MagicMock:
    """Build a Supabase mock whose schedule_log read returns `row`."""
    sb = MagicMock()
    chain = sb.from_.return_value
    chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = (
        [row] if row else []
    )
    # Update path mock — return whatever .execute() yields without error
    update_chain = sb.from_.return_value.update.return_value.eq.return_value
    update_chain.execute.return_value = MagicMock()
    return sb


def _row(scheduled: list[dict], gcal_event_ids: list[str], reviewed: bool = False) -> dict:
    return {
        "id": 1,
        "schedule_date": "2026-04-29",
        "proposed_json": _json.dumps({"scheduled": scheduled}),
        "gcal_event_ids": _json.dumps(gcal_event_ids),
        "gcal_write_calendar_id": "primary",
        "reviewed_at": "2026-04-29T22:00:00Z" if reviewed else None,
    }


def test_reconcile_today_no_row_returns_empty_delta():
    user_ctx = {
        "supabase": _mock_supabase_with_row(None),
        "user_id": "u1",
        "gcal_events": [],
        "todoist_active_ids": set(),
        "todoist_completed_ids": set(),
    }
    delta = reconcile_today(user_ctx, _date(2026, 4, 29))
    assert delta.has_writes() is False
    assert delta.skipped_reviewed is False


def test_reconcile_today_skips_when_reviewed():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    sb = _mock_supabase_with_row(_row([item], ["evt1"], reviewed=True))
    user_ctx = {
        "supabase": sb,
        "user_id": "u1",
        "gcal_events": [],
        "todoist_active_ids": set(),
        "todoist_completed_ids": set(),
    }
    delta = reconcile_today(user_ctx, _date(2026, 4, 29))
    assert delta.skipped_reviewed is True
    assert delta.has_writes() is False
    sb.from_.return_value.update.assert_not_called()


def test_reconcile_today_full_pass_persists_mutations():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    sb = _mock_supabase_with_row(_row([item], ["evt1"]))
    user_ctx = {
        "supabase": sb,
        "user_id": "u1",
        "gcal_events": [_gcal_event("evt1", "X", "2026-04-29T16:00:00+00:00", "2026-04-29T17:00:00+00:00")],
        "todoist_active_ids": {"t1"},
        "todoist_completed_ids": set(),
    }
    delta = reconcile_today(user_ctx, _date(2026, 4, 29))
    assert len(delta.moved) == 1
    assert delta.moved[0].new_start == "2026-04-29T16:00:00+00:00"
    sb.from_.return_value.update.assert_called_once()
    update_payload = sb.from_.return_value.update.call_args[0][0]
    persisted = _json.loads(update_payload["proposed_json"])
    assert persisted["scheduled"][0]["start_time"] == "2026-04-29T16:00:00+00:00"


def test_reconcile_today_drop_removes_item_and_event_id_in_sync():
    item_a = _scheduled_item("ta", "A", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    item_b = _scheduled_item("tb", "B", "2026-04-29T11:00:00+00:00", "2026-04-29T12:00:00+00:00", 60)
    sb = _mock_supabase_with_row(_row([item_a, item_b], ["evt_a", "evt_b"]))
    user_ctx = {
        "supabase": sb,
        "user_id": "u1",
        "gcal_events": [
            _gcal_event("evt_a", "A", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00"),
            _gcal_event("evt_b", "B", "2026-04-29T11:00:00+00:00", "2026-04-29T12:00:00+00:00"),
        ],
        "todoist_active_ids": {"tb"},  # ta is "deleted" — drop
        "todoist_completed_ids": set(),
    }
    delta = reconcile_today(user_ctx, _date(2026, 4, 29))
    assert len(delta.dropped) == 1
    assert delta.dropped[0].task_id == "ta"
    update_payload = sb.from_.return_value.update.call_args[0][0]
    persisted_scheduled = _json.loads(update_payload["proposed_json"])["scheduled"]
    persisted_event_ids = _json.loads(update_payload["gcal_event_ids"])
    assert len(persisted_scheduled) == 1
    assert persisted_scheduled[0]["task_id"] == "tb"
    assert persisted_event_ids == ["evt_b"]


def test_reconcile_today_no_writes_when_no_changes():
    item = _scheduled_item("t1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00", 60)
    sb = _mock_supabase_with_row(_row([item], ["evt1"]))
    user_ctx = {
        "supabase": sb,
        "user_id": "u1",
        "gcal_events": [_gcal_event("evt1", "X", "2026-04-29T09:00:00+00:00", "2026-04-29T10:00:00+00:00")],
        "todoist_active_ids": {"t1"},
        "todoist_completed_ids": set(),
    }
    delta = reconcile_today(user_ctx, _date(2026, 4, 29))
    assert delta.has_writes() is False
    sb.from_.return_value.update.assert_not_called()
