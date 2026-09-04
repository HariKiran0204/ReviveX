from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    service_name: str = "recoverai-api"
    cors_origins: str = "http://localhost:3000"

    database_url: str | None = None
    redis_url: str | None = None
    queue_name: str = "recoverai"
    worker_max_retries: int = Field(default=3, ge=0, le=10)

    payment_provider: str = "simulator"
    simulation_seed: int = 42

    llm_provider: str = "stub"
    llm_api_key: str | None = None

    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    max_retry_attempts: int = Field(default=3, ge=0)
    max_discount_percent: int = Field(default=10, ge=0, le=100)
    max_daily_discount_budget: int = Field(default=5000, ge=0)
    high_value_approval_threshold: int = Field(default=25000, ge=0)
    recovery_window_hours: int = Field(default=72, ge=1)
    recovery_ordering_grace_minutes: int = Field(default=60, ge=0)
    medium_value_approval_threshold: int = Field(default=5000, ge=0)
    max_communications_per_day: int = Field(default=3, ge=0)
    quiet_hours_start: int = Field(default=21, ge=0, le=23)
    quiet_hours_end: int = Field(default=8, ge=0, le=23)
    automatic_recovery_enabled: bool = True
    approval_ttl_minutes: int = Field(default=60, ge=1)

    @field_validator(
        "llm_api_key",
        "razorpay_key_id",
        "razorpay_key_secret",
        "razorpay_webhook_secret",
        "database_url",
        "redis_url",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_for_environment(self) -> None:
        if self.is_production and (not self.database_url or not self.redis_url):
            raise RuntimeError("DATABASE_URL and REDIS_URL are required when APP_ENV is production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_for_environment()
    return settings
