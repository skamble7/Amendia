# app/config.py
"""Service configuration.

All settings are read from the environment with the ``STUBEXC_`` prefix (or a
local ``.env`` file). Defaults are tuned for standalone dev; docker-compose
overrides the hosts to the ``mongodb`` / ``rabbitmq`` service names.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"
    MONGO_COLLECTION: str = "exceptions"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Service
    SERVICE_BASE_URL: str = "http://localhost:8081"
    DEFAULT_TENANT: str = "bank-alpha"
    HOST: str = "0.0.0.0"
    PORT: int = 8081
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="STUBEXC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
