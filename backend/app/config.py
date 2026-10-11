from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, StringConstraints, model_validator
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

    # Evaluator; evaluator_model falls back to claude_model when unset.
    evaluator_model: str | None = None
    evaluator_max_tokens: int = Field(default=2048, gt=0)
    evaluator_pass_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    evaluator_max_parse_attempts: int = Field(default=2, ge=1)

    # Ingestion. The embedding model must output 384-dimensional vectors (models.EMBEDDING_DIM).
    chunk_size: int = Field(default=800, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    embedding_model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        "all-MiniLM-L6-v2"
    )
    embedding_batch_size: int = Field(default=32, gt=0)

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
