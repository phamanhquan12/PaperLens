"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_root: Path = Path("outputs")

    gcp_project_id: str = "paperlens-dev-26"
    gcs_bucket_name: str = "paperlens-dev-26-paper-storage"

    docling_ocr_mode: Literal["off", "on", "auto"] = "auto"
    docling_images_scale: float = 1.5
    docling_threads: int = 1
    docling_do_formula_enrichment: bool = False
    docling_do_code_enrichment: bool = False

    luna_enabled: bool = False
    luna_provider: str = "openai"
    luna_model: str = ""
    luna_api_key: str | None = None
    luna_base_url: str | None = None
    luna_max_retries: int = 2
    luna_request_delay_seconds: float = 1.0
    luna_timeout_seconds: float = 60.0
    luna_prompt_version: str = "v1"
    luna_schema_version: str = "v1"
    allow_external_api: bool = False

    max_pdf_size_mb: int = 50
    asset_crop_padding_px: int = 8
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/paperlens.db"
    database_echo: bool = False
    ingest_async: bool = False

    embedding_provider: str = "hashing"
    embedding_model: str = ""
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_dimensions: int = 384
    retrieval_top_k: int = 8
    retrieval_use_mmr: bool = False

    @field_validator("local_storage_root", mode="before")
    @classmethod
    def _coerce_path(cls, value: object) -> Path:
        return Path(str(value))

    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
