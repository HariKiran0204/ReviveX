from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    service_name: str = "recoverai-worker"
    redis_url: str = "redis://localhost:6379/0"
    database_url: str | None = None
    queue_name: str = "recoverai"
    heartbeat_interval_seconds: int = 15
    worker_max_retries: int = Field(default=3, ge=0, le=10)

    @field_validator("redis_url", mode="before")
    @classmethod
    def require_redis_url(cls, value: object) -> object:
        if value == "":
            raise ValueError("REDIS_URL is required for the worker")
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url(cls, value: object) -> object:
        if value == "":
            return None
        return value


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
