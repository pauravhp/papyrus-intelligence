"""--sync command: CLI wrapper around src/sync_engine.run_sync."""

from datetime import date

from src.sync_engine import run_sync


def cmd_sync(context: dict, target_date: date, *, silent: bool = False) -> dict:
    """Reconcile task_history against Todoist for target_date."""
    return run_sync(context, target_date, silent=silent)
