# app/config.py
"""glea-service settings (ADR-058 Phase B). ``GLEA_``-prefixed env, mirroring the other platform
services. RabbitMQ carries the governed events; ClickHouse holds the audit_events system-of-record."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- RabbitMQ (audit-event consumer) ---
    RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"
    # Durable, named work-queue (competing consumers) — NOT the notification-service broadcast queue.
    # Named + durable so events queue while glea is down and are consumed on restart (no loss).
    AUDIT_QUEUE: str = "glea.audit_events"
    PREFETCH: int = 16
    # Brief pause before nack+requeue on a ClickHouse-unavailable insert, so a persistent CH outage
    # throttles the requeue loop instead of hot-looping. No-loss is preserved (still requeued).
    REQUEUE_BACKOFF_SECONDS: float = 2.0

    # --- ClickHouse (audit system-of-record; glea is the SOLE writer of audit_events) ---
    CLICKHOUSE_HOST: str = "clickhouse"
    CLICKHOUSE_PORT: int = 8123          # HTTP interface
    CLICKHOUSE_DB: str = "glea"          # glea's OWN database (the collector owns `otel`)
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_TABLE: str = "audit_events"
    # Max idle clients kept in the connection pool. Each concurrent operation borrows its OWN client
    # (clickhouse-connect clients are not safe to share across threads / concurrent queries), so a
    # backlog-drain burst reuses up to this many connections instead of churning them.
    CLICKHOUSE_POOL_SIZE: int = 8
    # Append-only audit horizon — long, configurable, and INDEPENDENT of the operational-trace TTL
    # (otel_traces is 72h; audit defaults to ~7 years). TTL is enforced on occurred_at.
    AUDIT_TTL_DAYS: int = 2555

    HOST: str = "0.0.0.0"
    PORT: int = 8090
    LOG_LEVEL: str = "INFO"
    ENABLE_DEV_CORS: bool = True

    model_config = SettingsConfigDict(
        env_prefix="GLEA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
