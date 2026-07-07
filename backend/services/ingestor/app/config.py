# app/config.py
"""Service configuration.

Settings are read from the environment with the ``INGESTOR_`` prefix (or a local
``.env`` file). Defaults target standalone dev; docker-compose overrides the
hosts to the ``mongodb`` / ``rabbitmq`` / ``stub-exception-generator`` services.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"
    MONGO_COLLECTION: str = "ingestions"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_QUEUE: str = "ingestor.exception_raised.v1"

    # Exception store (the stub) — fetch-back API base URL.
    STUB_BASE_URL: str = "http://localhost:8081"

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8082
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="INGESTOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
