from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(default="", min_length=0)
    google_client_secrets_file: str = "./client_secret.json"
    google_redirect_uri: str = "http://localhost:8080/oauth/callback"
    database_url: str = "sqlite+aiosqlite:///./mail_bot.db"
    encryption_key: str = ""
    poll_interval_seconds: int = Field(default=60, ge=10)
    max_attachment_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    oauth_state_ttl_seconds: int = Field(default=600, ge=60)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
