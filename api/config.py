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
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
