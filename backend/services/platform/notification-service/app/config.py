# app/config.py
"""Service configuration (env prefix ``NOTIFICATION_``).

The notification-service is a stateless fan-out relay: it consumes domain events
from RabbitMQ and pushes *thin invalidation signals* to browsers over SSE. It has
no database. It consumes ``amendia_auth`` only to require an authenticated bearer
on the SSE stream — being a downstream service, its ``AuthContext`` resolves
principals over HTTP against the identity service (the default resolver), though
the stream endpoint only needs bearer validation (``current_principal``).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from amendia_auth import AuthSettings, load_auth_settings


class Settings(BaseSettings):
    # Broker
    RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"

    # SSE fan-out tuning
    # Per-client bounded queue; a client that falls this far behind is resynced
    # (drop-oldest + a ``resync`` signal) rather than allowed to grow unbounded.
    CLIENT_QUEUE_MAXSIZE: int = 100
    # Heartbeat comment cadence — keeps idle SSE connections alive through proxies.
    HEARTBEAT_SECONDS: int = 20

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8088
    LOG_LEVEL: str = "INFO"

    # Dev-only permissive CORS (mirrors the other services).
    ENABLE_DEV_CORS: bool = True

    model_config = SettingsConfigDict(
        env_prefix="NOTIFICATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]

# Auth config for the SSE stream guard (NOTIFICATION_AUTH_ISSUER, _AUDIENCE, ...).
auth_settings: AuthSettings = load_auth_settings("NOTIFICATION_")
