from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/stock_scanner"

    # App
    app_env: str = "development"
    app_port: int = 8000
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # Security
    jwt_secret_key: str = "change-this-in-production-use-env-var"

    # Scheduler
    batch_cron_hour: int = 17
    batch_cron_minute: int = 30
    batch_timezone: str = "Asia/Seoul"

    # Data collection
    collect_retry_attempts: int = 3
    collect_retry_wait_seconds: int = 5
    pykrx_request_delay_ms: int = 200

    # Scan
    default_lookback_days: int = 60

    # KakaoTalk
    kakao_rest_api_key:    str = ""
    kakao_client_secret:   str = ""
    kakao_redirect_uri:    str = "http://localhost:8000/api/v1/notify/kakao/callback"

    # OpenAI
    openai_api_key:        str = ""
    openai_model:          str = "gpt-4o-mini"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
