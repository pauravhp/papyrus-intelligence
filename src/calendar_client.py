from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from src.models import CalendarEvent

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
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


def get_events(
    target_date: date,
    timezone_str: str = "America/Vancouver",
    extra_calendar_ids: list[str] | None = None,
) -> list[CalendarEvent]:
    """
    Fetch events from the primary calendar plus any IDs listed in extra_calendar_ids.

    extra_calendar_ids come from context.json["calendar_ids"] and let the user
    whitelist specific non-primary calendars without reading every calendar they
    have access to.
    """
    tz_str = _normalize_timezone(timezone_str)
    tz = ZoneInfo(tz_str)
    service = _get_calendar_service()

    start_of_day = datetime(target_date.year, target_date.month, target_date.day,
                            0, 0, 0, tzinfo=tz)
    end_of_day = datetime(target_date.year, target_date.month, target_date.day,
                          23, 59, 59, tzinfo=tz)

    time_min = start_of_day.isoformat()
    time_max = end_of_day.isoformat()

    cal_ids = ["primary"] + (extra_calendar_ids or [])

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
        except Exception:
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
