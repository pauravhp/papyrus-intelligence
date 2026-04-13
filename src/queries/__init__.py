"""
Re-exports all query functions for clean imports:
    from src.queries import insert_task_history, ...
"""

from src.queries.schedule_log import (
    compute_quality_score,
    delete_schedule_log_for_date,
    insert_schedule_log,
    update_quality_score,
)
from src.queries.sync import (
    append_sync_diff,
    get_task_ids_for_date,
    get_task_history_for_sync,
    get_user_injected_for_deletion_check,
    sync_apply_case_a,
    sync_apply_case_b,
    sync_apply_case_c,
    sync_inject_task,
)
from src.queries.task_history_reads import (
    get_reschedule_count,
    get_task_history_for_date,
    get_task_history_for_replan,
    get_task_history_row,
    get_todays_task_history,
)
from src.queries.task_history_writes import (
    _compute_time_bucket,
    delete_task_history_all,
    delete_task_history_row,
    insert_task_history,
    mark_task_partial,
    mark_task_rescheduled_externally,
    set_incomplete_reason,
    upsert_task_completed,
)

__all__ = [
    # schedule_log
    "compute_quality_score",
    "delete_schedule_log_for_date",
    "insert_schedule_log",
    "update_quality_score",
    # sync
    "append_sync_diff",
    "get_task_ids_for_date",
    "get_task_history_for_sync",
    "get_user_injected_for_deletion_check",
    "sync_apply_case_a",
    "sync_apply_case_b",
    "sync_apply_case_c",
    "sync_inject_task",
    # task_history reads
    "get_reschedule_count",
    "get_task_history_for_date",
    "get_task_history_for_replan",
    "get_task_history_row",
    "get_todays_task_history",
    # task_history writes
    "_compute_time_bucket",
    "delete_task_history_all",
    "delete_task_history_row",
    "insert_task_history",
    "mark_task_partial",
    "mark_task_rescheduled_externally",
    "set_incomplete_reason",
    "upsert_task_completed",
]
