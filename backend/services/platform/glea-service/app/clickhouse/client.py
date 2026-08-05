# app/clickhouse/client.py
"""ClickHouse connection + one-time schema bootstrap for glea-service.

Uses the synchronous ``clickhouse-connect`` HTTP client; callers run its blocking calls off the event
loop via ``asyncio.to_thread`` (the writer/reader do). ``StorageUnavailable`` is the single exception the
consumer treats as "keep the message" (nack + requeue) — every other error is a poison message.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.clickhouse import schema
from app.config import settings

logger = logging.getLogger(__name__)


class StorageUnavailable(Exception):
    """ClickHouse is unreachable/erroring at the transport level — the caller must NOT drop the
    in-flight event; requeue it so nothing is lost when the store recovers."""


def connect() -> Any:
    """Open a ClickHouse client. Raises ``StorageUnavailable`` when the server can't be reached.

    ``autogenerate_session_id=False`` makes the client **sessionless** — clickhouse-connect's HTTP
    session forbids concurrent queries within one session ("Attempt to execute concurrent queries
    within the same session"), and glea runs the consumer's inserts and the read API concurrently.
    Sessionless removes the session, but a single ``Client`` object is still not safe to share across
    threads — the connection POOL is the real fix: each concurrent operation borrows its OWN client
    (see provider.py). One client is thus never used by two threads at once."""
    import clickhouse_connect

    try:
        return clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            # Connect to the default database; every statement fully-qualifies `glea.audit_events`, so
            # the target DB need not exist at connect time (bootstrap creates it).
            connect_timeout=10,
            send_receive_timeout=30,
            autogenerate_session_id=False,   # sessionless: no shared session_id to collide on
        )
    except Exception as exc:  # noqa: BLE001
        raise StorageUnavailable(f"clickhouse connect failed: {exc}") from exc


def bootstrap(client: Any) -> None:
    """Create the ``glea`` database + ``audit_events`` table if absent (idempotent). Safe to call on
    every startup; the collector's ``otel`` DB is untouched — glea owns its own database."""
    db, table, ttl = settings.CLICKHOUSE_DB, settings.CLICKHOUSE_TABLE, settings.AUDIT_TTL_DAYS
    client.command(schema.create_database_ddl(db))
    client.command(schema.create_table_ddl(db, table, ttl))
    logger.info("audit_events schema ready: %s.%s (ttl=%dd)", db, table, ttl)


def ping(client: Optional[Any]) -> bool:
    if client is None:
        return False
    try:
        client.command("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
