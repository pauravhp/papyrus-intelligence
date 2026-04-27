"""
API settings — loaded from .env at startup.

All secrets are required. FastAPI will refuse to start if any are missing.
Never import settings directly from this module; use the `settings` singleton:

    from api.config import settings
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_SECRET_KEY: str   # sb_secret_... from Settings → API Keys
    ENCRYPTION_KEY: str        # used for HMAC state signing in OAuth flows

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    TODOIST_CLIENT_ID: str        # new — required
    TODOIST_CLIENT_SECRET: str    # new — required
    ANTHROPIC_API_KEY: str        # now required (was Optional)
    POSTHOG_API_KEY: str = ""   # empty string disables PostHog in local dev without the key
    FRONTEND_URL: str = "http://localhost:3000"
    # Public URL the backend is reachable at — used to construct OAuth callback
    # URIs that Google and Todoist redirect the user's browser to. Must match
    # the redirect URIs registered in each provider's developer console.
    BACKEND_URL: str = "http://localhost:8001"
    BETA_ALLOWLIST: str = ""    # comma-separated emails; empty = open access (dev/test)
    BACKEND_CORS_ORIGINS: str = "http://localhost:3000"  # comma-separated

    # Feature flags — keep in sync with NEXT_PUBLIC_* counterparts on the frontend.
    COACHING_NUDGES_ENABLED: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
