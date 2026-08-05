# app/clickhouse/provider.py
"""Lazy, self-healing ClickHouse client provider.

The store may be down at startup or bounce mid-run; glea must never crash on that (fail-soft) and must
never drop an audit event. So the client is connected + the schema bootstrapped on FIRST use under a
lock, cached, and rebuilt on the next call if it was torn down. Any failure surfaces as
``StorageUnavailable`` — the consumer turns that into nack+requeue, the read API into 503.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.clickhouse.client import bootstrap, connect

logger = logging.getLogger(__name__)


class ClickHouseProvider:
    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._lock = asyncio.Lock()

    def _build(self) -> Any:
        client = connect()      # raises StorageUnavailable
        bootstrap(client)       # CREATE DATABASE/TABLE IF NOT EXISTS (idempotent)
        return client

    async def ensure(self) -> Any:
        """Return a ready client, connecting + bootstrapping on first use. Raises ``StorageUnavailable``
        when the store is unreachable (the caller decides: requeue / 503)."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build)
                logger.info("clickhouse client ready")
            return self._client

    def current(self) -> Optional[Any]:
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
