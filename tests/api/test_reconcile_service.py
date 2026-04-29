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
