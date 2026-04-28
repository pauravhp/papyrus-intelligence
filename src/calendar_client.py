from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.models import CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
WRITE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
]
TOKEN_PATH = Path(__file__).parent.parent / "token.json"
CREDS_PATH = Path(__file__).parent.parent / "credentials.json"

_TIMEZONE_ALIASES = {
    "PST": "America/Vancouver",
    "PST/Vancouver": "America/Vancouver",
    "Vancouver": "America/Vancouver",
}


def _normalize_timezone(tz_str: str) -> str:
    return _TIMEZONE_ALIASES.get(tz_str, tz_str)


def _get_calendar_service():
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "token.json not found. Run the OAuth flow (test_gcal.py) to generate it."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "GCal token is expired and cannot be refreshed. Re-run the OAuth flow."
            )

    return build("calendar", "v3", credentials=creds)


def list_calendars(service) -> list[dict]:
    """List all GCal calendars with metadata. Used by GET /api/calendars — never at scheduling time."""
    try:
        items = service.calendarList().list().execute().get("items", [])
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary", cal["id"]),
                "background_color": cal.get("backgroundColor", "#4285f4"),
                "access_role": cal.get("accessRole", "reader"),
            }
            for cal in items
        ]
    except Exception as exc:
        import sys
        print(f"[list_calendars] calendarList failed: {exc}", file=sys.stderr)
        return [{"id": "primary", "summary": "Primary", "background_color": "#4285f4", "access_role": "owner"}]


def _detect_user_timezone(service) -> str | None:
    """Fetch the timezone set on the user's primary GCal calendar."""
    try:
        cal = service.calendars().get(calendarId="primary").execute()
        return cal.get("timeZone")
    except Exception:
        return None


def get_events(
    target_date: date,
    timezone_str: str = "America/Vancouver",
    calendar_ids: list[str] | None = None,
    service=None,
) -> list[CalendarEvent]:
    """
    Fetch GCal events for target_date from the given calendar_ids.

    calendar_ids — explicit list of calendar IDs to query. Callers are responsible
    for applying the fallback chain:
        config.get("source_calendar_ids") or config.get("calendar_ids") or ["primary"]
    If empty or None, returns [] immediately.

    service — pre-built googleapiclient service object. When None (CLI path),
    _get_calendar_service() reads credentials from token.json on disk.
    Pass an explicit service to use caller-managed credentials (API path).
    """
    if not calendar_ids:
        return []

    if service is None:
        service = _get_calendar_service()

    tz_str = _normalize_timezone(timezone_str)
    # Auto-detect timezone from GCal when config is unset (UTC default)
    if tz_str == "UTC":
        detected = _detect_user_timezone(service)
        if detected:
            tz_str = _normalize_timezone(detected)

    tz = ZoneInfo(tz_str)

    start_of_day = datetime(target_date.year, target_date.month, target_date.day,
                            0, 0, 0, tzinfo=tz)
    end_of_day = datetime(target_date.year, target_date.month, target_date.day,
                          23, 59, 59, tzinfo=tz)

    time_min = start_of_day.isoformat()
    time_max = end_of_day.isoformat()

    cal_ids = calendar_ids

    seen_ids: set[str] = set()
    events: list[CalendarEvent] = []

    for cal_id in cal_ids:
        try:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
        except Exception as exc:
            import sys
            print(f"[get_events] calendar {cal_id!r} failed: {exc}", file=sys.stderr)
            continue  # skip calendars we can't read

        for item in result.get("items", []):
            event_id = item.get("id", "")
            if event_id in seen_ids:
                continue  # deduplicate (same event can appear in multiple calendars)
            seen_ids.add(event_id)

            start_raw = item.get("start", {})
            end_raw = item.get("end", {})

            is_all_day = "date" in start_raw and "dateTime" not in start_raw

            if is_all_day:
                start_dt = datetime.strptime(start_raw["date"], "%Y-%m-%d").replace(tzinfo=tz)
                end_dt = datetime.strptime(end_raw["date"], "%Y-%m-%d").replace(tzinfo=tz)
            else:
                start_dt = datetime.fromisoformat(start_raw["dateTime"])
                end_dt = datetime.fromisoformat(end_raw["dateTime"])
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=tz)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=tz)

            events.append(CalendarEvent(
                id=event_id,
                summary=item.get("summary", "(No title)"),
                start=start_dt,
                end=end_dt,
                color_id=item.get("colorId"),
                is_all_day=is_all_day,
            ))

    events.sort(key=lambda e: e.start)
    return events


def build_gcal_service_from_credentials(
    creds_data: dict,
    client_id: str,
    client_secret: str,
):
    """
    Build a googleapiclient service from a stored credentials dict.
    Refreshes the token if expired. Caller is responsible for writing
    the refreshed creds back to Supabase.

    Returns (service, refreshed_creds_dict | None).
    If creds were not refreshed, second element is None.
    """
    creds = Credentials.from_authorized_user_info(creds_data, scopes=WRITE_SCOPES)
    creds._client_id = client_id
    creds._client_secret = client_secret

    refreshed: dict | None = None
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            import json as _json
            refreshed = _json.loads(creds.to_json())
        else:
            raise RuntimeError("GCal token is invalid and cannot be refreshed.")

    service = build("calendar", "v3", credentials=creds)
    return service, refreshed


def create_event(
    service,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    timezone_str: str,
    calendar_id: str = "primary",
) -> str:
    """Create a GCal event. Returns the new event's id."""
    body = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_str},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_str},
    }
    result = service.events().insert(calendarId=calendar_id, body=body).execute()
    return result["id"]


def delete_event(
    service,
    event_id: str,
    calendar_id: str = "primary",
) -> None:
    """Delete a GCal event by id. Silently ignores 404."""
    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    except Exception as exc:
        if "404" not in str(exc) and "notFound" not in str(exc):
            raise
