# app/clickhouse/provider.py
"""A small, self-healing ClickHouse connection POOL for glea-service.

The bug this replaces: a single cached ``clickhouse-connect`` client was returned to every caller — the
async consumer's inserts (run via ``asyncio.to_thread``) and every read-API query. That client carries an
HTTP session that forbids concurrent queries, so under real load ("consumer draining the queue while the
read API polls") queries collided → every insert failed → requeue storm → ``audit_events`` stayed empty →
reads 503'd.

The fix: each concurrent operation borrows its OWN client from a bounded pool, uses it in exactly one
thread, and returns it. No ``Client`` object is ever used by two threads at once (clients are also
sessionless — see ``client.connect``). The pool caps idle clients (``CLICKHOUSE_POOL_SIZE``) so a
backlog-drain burst reuses connections instead of churning them.

Still fail-soft + self-healing: a failed connect / bootstrap / query surfaces as ``StorageUnavailable``
(consumer → nack+requeue, read API → 503); the schema is bootstrapped once, lazily, on the first
successful borrow, and retried on the next borrow if ClickHouse was down.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import contextmanager
from typing import Any, Callable, List, Optional

from app.clickhouse.client import StorageUnavailable, bootstrap, connect
from app.config import settings

logger = logging.getLogger(__name__)


def _safe_close(client: Any) -> None:
    try:
        client.close()
    except Exception:  # noqa: BLE001
        pass


class ClickHousePool:
    """A bounded pool of sessionless clients, each borrowed exclusively per operation.

    ``connect_fn`` / ``bootstrap_fn`` are injectable for tests (a fake that models the "one session = no
    concurrent queries" constraint), defaulting to the real ClickHouse ``connect``/``bootstrap``.
    """

    def __init__(self, *, max_idle: Optional[int] = None,
                 connect_fn: Callable[[], Any] = connect,
                 bootstrap_fn: Callable[[Any], None] = bootstrap) -> None:
        self._max_idle = max_idle if max_idle is not None else getattr(settings, "CLICKHOUSE_POOL_SIZE", 8)
        self._connect = connect_fn
        self._bootstrap = bootstrap_fn
        self._idle: List[Any] = []
        self._lock = threading.Lock()
        self._bootstrapped = False
        self._boot_lock = threading.Lock()

    # -- checkout / checkin (thread-safe; the pool is used from worker threads) --
    def _checkout(self) -> Any:
        with self._lock:
            if self._idle:
                return self._idle.pop()
        return self._connect()  # sessionless client; raises StorageUnavailable on connect failure

    def _checkin(self, client: Any, healthy: bool) -> None:
        # A client that errored may be in a bad state — drop it rather than pool it.
        if not healthy:
            _safe_close(client)
            return
        with self._lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(client)
                return
        _safe_close(client)  # pool full → close the excess

    def _ensure_bootstrap(self, client: Any) -> None:
        """Idempotent schema bootstrap, run exactly once on the first healthy borrow. Retried on a later
        borrow if ClickHouse was down (the flag stays False until it succeeds)."""
        if self._bootstrapped:
            return
        with self._boot_lock:
            if self._bootstrapped:
                return
            try:
                self._bootstrap(client)
            except StorageUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                raise StorageUnavailable(f"schema bootstrap failed: {exc}") from exc
            self._bootstrapped = True

    @contextmanager
    def borrow(self):
        """Borrow a client for one operation, exclusively (never handed to another thread concurrently).
        Ensures the schema exists on first use. On any error the client is closed (not returned)."""
        client = self._checkout()  # may raise StorageUnavailable
        healthy = True
        try:
            self._ensure_bootstrap(client)
            yield client
        except Exception:
            healthy = False
            raise
        finally:
            self._checkin(client, healthy)

    def run_sync(self, fn: Callable[[Any], Any]) -> Any:
        """Run ``fn(client)`` against a freshly-borrowed client. Call from a worker thread."""
        with self.borrow() as client:
            return fn(client)

    async def run(self, fn: Callable[[Any], Any]) -> Any:
        """Run ``fn(client)`` off the event loop, each call on its OWN borrowed client."""
        return await asyncio.to_thread(self.run_sync, fn)

    def warm(self) -> None:
        """Best-effort startup bootstrap (borrow one client + create the schema). Never raises to the
        caller beyond StorageUnavailable — main() swallows it, and it self-heals on the first event."""
        with self.borrow():
            pass

    def close(self) -> None:
        with self._lock:
            clients, self._idle = self._idle, []
        for c in clients:
            _safe_close(c)
