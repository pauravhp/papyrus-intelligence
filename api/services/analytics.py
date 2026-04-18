"""
PostHog event capture — fire-and-forget wrapper.

Always call via FastAPI BackgroundTasks in route handlers, or inline
with a try/except in non-route code (e.g. agent_tools.py).
The PostHog SDK queues events in a background thread, so calls are
non-blocking regardless.
"""

import posthog

from api.config import settings

posthog.project_api_key = settings.POSTHOG_API_KEY
posthog.host = "https://us.i.posthog.com"


def capture(user_id: str, event: str, properties: dict | None = None) -> None:
    """Send a PostHog event. Never raises — analytics must not affect user flows."""
    try:
        posthog.capture(
            distinct_id=user_id,
            event=event,
            properties=properties or {},
        )
    except Exception as exc:
        print(f"[analytics] capture failed for {event}: {exc}")
