"""
Supabase-backed CRUD for public.project_budgets.

All functions take (user_id, supabase_client, ...) — no SQLite, no global state.
compute_deadline_pressure is imported from src.queries.budgets (pure logic, no DB).
"""

from datetime import datetime

from src.queries.budgets import compute_deadline_pressure


def _add_pressure(row: dict) -> dict:
    row["deadline_pressure"] = compute_deadline_pressure(
        row.get("deadline"), float(row.get("remaining_hours", 0))
    )
    return row


def get_active_projects(user_id: str, supabase) -> list[dict]:
    """Return all project_budgets rows with remaining_hours > 0, pressure annotated."""
    result = (
        supabase.from_("project_budgets")
        .select("*")
        .eq("user_id", user_id)
        .gt("remaining_hours", 0)
        .order("priority", desc=True)
        .execute()
    )
    return [_add_pressure(r) for r in (result.data or [])]


def create_project(
    user_id: str,
    supabase,
    name: str,
    total_hours: float,
    session_min: int = 60,
    session_max: int = 180,
    deadline: str | None = None,
    priority: int = 3,
) -> dict:
    """Insert a new project_budgets row. remaining_hours starts at total_hours."""
    now = datetime.now().isoformat()
    row = {
        "user_id": user_id,
        "project_name": name,
        "total_budget_hours": total_hours,
        "remaining_hours": total_hours,
        "session_min_minutes": session_min,
        "session_max_minutes": session_max,
        "deadline": deadline,
        "priority": priority,
        "created_at": now,
        "updated_at": now,
    }
    result = supabase.from_("project_budgets").insert(row).execute()
    return _add_pressure(result.data[0])


def update_project(
    user_id: str,
    supabase,
    project_id: int,
    session_min: int | None = None,
    session_max: int | None = None,
    deadline: str | None = None,
    priority: int | None = None,
    add_hours: float | None = None,
) -> dict:
    """Patch individual fields. add_hours adjusts remaining_hours (capped at total)."""
    updates: dict = {"updated_at": datetime.now().isoformat()}
    if session_min is not None:
        updates["session_min_minutes"] = session_min
    if session_max is not None:
        updates["session_max_minutes"] = session_max
    if deadline is not None:
        updates["deadline"] = deadline
    if priority is not None:
        updates["priority"] = priority
    if add_hours is not None:
        current = (
            supabase.from_("project_budgets")
            .select("remaining_hours, total_budget_hours")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
            .data
        )
        if current:
            new_remaining = min(
                float(current["total_budget_hours"]),
                float(current["remaining_hours"]) + add_hours,
            )
            updates["remaining_hours"] = new_remaining

    result = (
        supabase.from_("project_budgets")
        .update(updates)
        .eq("id", project_id)
        .eq("user_id", user_id)
        .select()
        .single()
        .execute()
    )
    return _add_pressure(result.data)


def delete_project(user_id: str, supabase, project_id: int) -> None:
    """Hard delete a project_budgets row."""
    supabase.from_("project_budgets").delete().eq("id", project_id).eq("user_id", user_id).execute()


def reset_project(user_id: str, supabase, project_id: int) -> dict:
    """Reset remaining_hours back to total_budget_hours."""
    current = (
        supabase.from_("project_budgets")
        .select("total_budget_hours")
        .eq("id", project_id)
        .eq("user_id", user_id)
        .single()
        .execute()
        .data
    )
    total = float(current["total_budget_hours"]) if current else 0.0
    result = (
        supabase.from_("project_budgets")
        .update({"remaining_hours": total, "updated_at": datetime.now().isoformat()})
        .eq("id", project_id)
        .eq("user_id", user_id)
        .select()
        .single()
        .execute()
    )
    return _add_pressure(result.data)


def log_session(user_id: str, supabase, project_id: int, hours_worked: float) -> dict:
    """
    Subtract hours_worked from remaining_hours (floor 0).
    Returns updated row with deadline_pressure annotated.
    This is the only budget decay path — no auto-decrement on confirm_schedule.
    """
    current = (
        supabase.from_("project_budgets")
        .select("remaining_hours")
        .eq("id", project_id)
        .eq("user_id", user_id)
        .single()
        .execute()
        .data
    )
    new_remaining = max(0.0, float(current["remaining_hours"]) - hours_worked) if current else 0.0
    result = (
        supabase.from_("project_budgets")
        .update({"remaining_hours": new_remaining, "updated_at": datetime.now().isoformat()})
        .eq("id", project_id)
        .eq("user_id", user_id)
        .select()
        .single()
        .execute()
    )
    return _add_pressure(result.data)
