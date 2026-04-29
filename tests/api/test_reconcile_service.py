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
