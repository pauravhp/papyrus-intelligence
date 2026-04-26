"""
Detect whether the user has Todoist's Google Calendar integration enabled.

When that integration is on, Todoist mirrors every task with a `due_datetime`
into the user's GCal as its own event. Combined with Papyrus's own direct
GCal writes (planner.confirm + replan_confirm), the result is two events on
the calendar for every confirmed task. See PRE-RELEASE.md #9.

Todoist does not expose an API to toggle their integration, so the only fix
is detection + asking the user to flip the toggle in Todoist's web UI.

Detection signal (single, by design): Todoist's mirrored events live on a
dedicated calendar that Todoist creates with the summary "Todoist". We scan
the user's GCal calendar list for any whose summary starts with "todoist"
(case-insensitive). The PRE-RELEASE doc explains why we don't bother with a
second title-overlap signal.
"""

from __future__ import annotations

from src.calendar_client import list_calendars


def detect_todoist_gcal_sync(gcal_service) -> dict:
    """Return {"detected": bool, "calendar_id": str | None}.

    Detected when any calendar in the user's calendar list has a summary
    starting with "todoist" (case-insensitive). Returns the first match's id.
    """
    calendars = list_calendars(gcal_service) or []
    for cal in calendars:
        summary = (cal.get("summary") or "").strip().lower()
        if summary.startswith("todoist"):
            return {"detected": True, "calendar_id": cal.get("id")}
    return {"detected": False, "calendar_id": None}
