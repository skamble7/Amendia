# app/hub.py
"""In-process fan-out hub: one RabbitMQ consumer → many SSE clients.

Each connected browser gets its own bounded ``asyncio.Queue``. The RabbitMQ
consumer callback calls ``publish(signal)`` which non-blocking-offers the signal to
every subscriber. A client that falls too far behind (its queue fills) has its
backlog **collapsed to a single ``resync`` signal** — the browser then re-fetches
everything through the authoritative REST endpoints rather than replaying a stale
backlog, and one slow client can never block the consumer.

Single-process only: this hub fans out within one notification-service process. A
multi-replica deployment would need a shared bus (e.g. Redis pub/sub) so every
replica sees every event — deliberately deferred (dev/prod is single-container).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

# Sentinel a lagging client receives to trigger a full re-sync (invalidate-all).
RESYNC_SIGNAL: Dict[str, Any] = {"type": "resync"}


class NotificationHub:
    def __init__(self, *, client_queue_maxsize: int = 100) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._maxsize = client_queue_maxsize

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, signal: Dict[str, Any]) -> None:
        """Non-blocking fan-out to every subscriber. Never awaits, never raises."""
        for q in list(self._subscribers):
            self._offer(q, signal)

    def _offer(self, q: asyncio.Queue, signal: Dict[str, Any]) -> None:
        try:
            q.put_nowait(signal)
        except asyncio.QueueFull:
            # Slow consumer: drop its whole backlog and leave a single resync.
            # Safe because put_nowait/get_nowait don't await, so the reader (which
            # does `await q.get()`) can't interleave mid-collapse.
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - defensive
                    break
            try:
                q.put_nowait(RESYNC_SIGNAL)
            except asyncio.QueueFull:  # pragma: no cover - maxsize>=1 always fits one
                pass
            logger.warning("SSE client fell behind; collapsed backlog to a resync")

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
