# app/config.py
"""Service configuration.

All settings are read from the environment with the ``STUBEXC_`` prefix (or a
local ``.env`` file). Defaults are tuned for standalone dev; docker-compose
overrides the hosts to the ``mongodb`` / ``rabbitmq`` service names.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from amendia_auth import AuthSettings, load_auth_settings


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

    # Dev-only permissive CORS so a separately-served webui can call this
    # service directly. The Vite/nginx proxy avoids CORS in the normal setup;
    # this is default-on in compose and should be disabled in production.
    ENABLE_DEV_CORS: bool = True

    model_config = SettingsConfigDict(
        env_prefix="STUBEXC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]

# Auth config (STUBEXC_AUTH_ISSUER, _AUDIENCE, _JWKS_URI, _IDENTITY_BASE_URL,
# _INTERNAL_TOKEN, _COMPAT_STUB, ...).
auth_settings: AuthSettings = load_auth_settings("STUBEXC_")
