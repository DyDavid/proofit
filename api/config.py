"""Settings loaded from the environment / `.env` (see `.env.example`).

Field names match `.env.example` exactly so the two files never drift.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    engine_mode: Literal["mock", "live"] = "mock"
    app_version: str = "0.1.0"
    mock_delay_seconds: float = 1.5
    max_upload_bytes: int = 5 * 1024 * 1024
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_api_key: str | None = None

    supabase_url: str | None = None
    supabase_service_key: str | None = None
    supabase_key: str | None = None


settings = Settings()

