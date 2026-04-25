"""Application configuration loaded from environment (.env) via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. All values come from environment or the .env file."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")

    # X API (OAuth 2.0 app credentials)
    x_client_id: str = Field("", alias="X_CLIENT_ID")
    x_client_secret: str = Field("", alias="X_CLIENT_SECRET")
    x_user_numeric_id: str = Field("", alias="X_USER_NUMERIC_ID")
    x_username: str = Field("", alias="X_USERNAME")
    x_redirect_uri: str = Field(
        "http://localhost:8765/callback", alias="X_REDIRECT_URI"
    )
    x_refresh_token: str = Field("", alias="X_REFRESH_TOKEN")

    # Anthropic
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    # Dashboard
    dashboard_username: str = Field("", alias="DASHBOARD_USERNAME")
    dashboard_password: str = Field("", alias="DASHBOARD_PASSWORD")

    # App
    app_host: str = Field("127.0.0.1", alias="APP_HOST")
    app_port: int = Field(8000, alias="APP_PORT")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Scheduler intervals (seconds). Default daily — home-timeline jobs aren't
    # time-sensitive enough to justify hourly pulls, and X charges per tweet.
    feed_pull_interval: int = Field(86400, alias="FEED_PULL_INTERVAL")

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def refresh_token_file(self) -> Path:
        """File fallback for the rotating X refresh token (used if .env is read-only)."""
        return PROJECT_ROOT / "secrets" / "x_refresh_token"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
