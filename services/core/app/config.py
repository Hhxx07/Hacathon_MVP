from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "development"
    secret_key: str = "development-only-secret-change-me"
    database_url: str = "sqlite+aiosqlite:///./data/study.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    access_token_minutes: int = 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        return [item.strip() for item in value.split(",")] if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()

