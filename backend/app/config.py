from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RELI-RAG API"
    database_url: str
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    max_upload_mb: int = 20
    similarity_gate: float = Field(default=0.30, ge=-1.0, le=1.0)

    anthropic_api_key: SecretStr | None = None
    claude_model: str | None = None
    claude_max_tokens: int = Field(default=1024, gt=0)
    claude_timeout_seconds: float = Field(default=60.0, gt=0)
    claude_retry_backoff_seconds: float = Field(default=1.0, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
