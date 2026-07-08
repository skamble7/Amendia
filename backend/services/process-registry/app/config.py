# app/config.py
"""Service configuration (env prefix ``REGISTRY_``)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Default seed dir: the agent-runtime seed the registry onboards through its own APIs.
#   config.py -> app -> <service root> -> services
_SERVICES_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SEED_DIR = str(_SERVICES_DIR / "agent-runtime" / "seed" / "wire-repair-standard")


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"

    # Seeding (drives the seed dataset through the real onboarding APIs)
    SEED_DIR: str = _DEFAULT_SEED_DIR
    SEED_ON_STARTUP: bool = False

    # /resolve active-pack cache TTL (seconds)
    RESOLVE_CACHE_TTL: float = 30.0

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8084
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="REGISTRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
