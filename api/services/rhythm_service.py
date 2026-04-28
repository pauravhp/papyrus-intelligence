"""
Supabase-backed CRUD for public.rhythms.

No budget tracking — rhythms are recurring weekly commitments with a cadence,
not a finite pool of hours. All functions take (user_id, supabase_client, ...).
"""

from datetime import date, datetime

# Sentinel: distinguishes "description not supplied to update_rhythm" from
# "description explicitly set to None (clear to NULL)".
_DESCRIPTION_UNSET = object()
_DAYS_UNSET = object()


def get_active_rhythms(user_id: str, supabase) -> list[dict]:
    """Return rhythms where end_date IS NULL or end_date >= today, sorted by sort_order."""
    today = date.today().isoformat()
    result = (
        supabase.from_("rhythms")
        .select("*")
        .eq("user_id", user_id)
        .or_(f"end_date.is.null,end_date.gte.{today}")
        .order("sort_order")
        .execute()
    )
    return result.data or []


def create_rhythm(
    user_id: str,
    supabase,
    name: str,
    sessions_per_week: int,
    session_min: int = 60,
    session_max: int = 120,
    end_date: str | None = None,
    sort_order: int = 0,
    description: str | None = None,
    days_of_week: list[str] | None = None,
) -> dict:
    """Insert a new rhythm. Returns the created row."""
    now = datetime.now().isoformat()
    row = {
        "user_id": user_id,
        "rhythm_name": name,
        "sessions_per_week": sessions_per_week,
        "session_min_minutes": session_min,
        "session_max_minutes": session_max,
        "end_date": end_date,
        "sort_order": sort_order,
        "description": description,
        "days_of_week": days_of_week,
        "created_at": now,
        "updated_at": now,
    }
    result = supabase.from_("rhythms").insert(row).execute()
    return result.data[0]


def update_rhythm(
    user_id: str,
    supabase,
    rhythm_id: int,
    sessions_per_week: int | None = None,
    session_min: int | None = None,
    session_max: int | None = None,
    end_date: str | None = None,
    sort_order: int | None = None,
    description=_DESCRIPTION_UNSET,  # str | None | _DESCRIPTION_UNSET
    days_of_week=_DAYS_UNSET,  # list[str] | None | _DAYS_UNSET
) -> dict:
    """Patch individual fields. Returns the updated row."""
    updates: dict = {"updated_at": datetime.now().isoformat()}
    if sessions_per_week is not None:
        updates["sessions_per_week"] = sessions_per_week
    if session_min is not None:
        updates["session_min_minutes"] = session_min
    if session_max is not None:
        updates["session_max_minutes"] = session_max
    if end_date is not None:
        updates["end_date"] = end_date
    if sort_order is not None:
        updates["sort_order"] = sort_order
    if description is not _DESCRIPTION_UNSET:
        # None → stored as NULL (clear); non-empty str → stored as-is
        updates["description"] = description
    if days_of_week is not _DAYS_UNSET:
        updates["days_of_week"] = days_of_week

    result = (
        supabase.from_("rhythms")
        .update(updates)
        .eq("id", rhythm_id)
        .eq("user_id", user_id)
        .select()
        .single()
        .execute()
    )
    return result.data


def delete_rhythm(user_id: str, supabase, rhythm_id: int) -> None:
    """Hard delete a rhythm row."""
    (
        supabase.from_("rhythms")
        .delete()
        .eq("id", rhythm_id)
        .eq("user_id", user_id)
        .execute()
    )
