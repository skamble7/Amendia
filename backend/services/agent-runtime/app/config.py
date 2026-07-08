# app/config.py
"""Service configuration (env prefix ``AGENTRT_``)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Default seed directory: <service-root>/seed/wire-repair-standard
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SEED_DIR = str(_SERVICE_ROOT / "seed" / "wire-repair-standard")


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"
    # LangGraph checkpointer collections (runtime-private, same db).
    CHECKPOINT_COLLECTION: str = "lg_checkpoints"
    CHECKPOINT_WRITES_COLLECTION: str = "lg_checkpoint_writes"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_DISPATCH_QUEUE: str = "agent-runtime.exception_dispatched.v1"

    # Process registry — pack/capability/schema/resolution API.
    REGISTRY_BASE_URL: str = "http://localhost:8084"
    # Envelope fetch + registry HTTP timeout (seconds).
    HTTP_TIMEOUT: int = 15
    # This service's own base URL (used in HITL task context_url).
    SELF_BASE_URL: str = "http://localhost:8083"

    # Capability execution: simulation seam (no external LLM/MCP calls).
    SIMULATION_MODE: bool = True

    # Debug/dev surfaces (guarded like the seed API).
    ENABLE_DEBUG_API: bool = True

    # Seeding
    SEED_DIR: str = _DEFAULT_SEED_DIR
    ENABLE_SEED_API: bool = True
    SEED_ON_STARTUP: bool = False

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8083
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="AGENTRT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
