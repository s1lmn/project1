from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://sports_mate:sports_mate@localhost:5432/sports_mate"
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webapp_url: str = "http://localhost:5173"
    telegram_notifications_enabled: bool = False
    web_api_url: str = "http://localhost:8000"
    allowed_origins: list[str] | str = ["http://localhost:5173"]
    session_secret: str = "development-only-change-me-please-32"
    session_ttl_seconds: int = 86_400
    telegram_init_data_max_age_seconds: int = 3_600
    enable_dev_auth: bool = False
    cluster_timezone: str = "Europe/Moscow"
    activity_ttl_hours: int = 48
    reminder_minutes_before: int = 60
    result_request_minutes_after: int = 120
    auto_complete_hours_after: int = 24
    worker_poll_seconds: int = 15
    notification_max_attempts: int = 5
    internal_api_key: str = ""
    sentry_dsn: str = ""
    log_level: str = "INFO"
    auth_rate_limit_per_minute: int = 10
    write_rate_limit_per_minute: int = 30
    report_rate_limit_per_minute: int = 10
    analytics_rate_limit_per_minute: int = 120
    min_user_age: int = 18
    max_user_age: int = 100
    min_players_needed: int = 1
    max_players_needed: int = 5

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_v3(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("enable_dev_auth")
    @classmethod
    def dev_auth_only_locally(cls, value: bool, info):
        env = info.data.get("app_env", "development")
        if value and env not in {"development", "test"}:
            raise ValueError("ENABLE_DEV_AUTH разрешён только в development/test")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
