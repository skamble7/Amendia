# app/routers/stream.py
"""The SSE endpoint: ``GET /stream``.

Authenticated (any valid bearer — ``current_principal``); no role required, because
signals are thin and the real data is re-fetched through the role-guarded REST APIs.
Each connection subscribes to the fan-out hub and streams signals as ``data:`` lines,
with a ``: ping`` comment every ``HEARTBEAT_SECONDS`` so idle connections survive
proxies. An initial ``event: ready`` lets the browser flip its status to "up" and
trigger a full resync (catching anything missed while it was disconnected).

The stream body is the standalone ``sse_stream`` async generator so it can be unit
tested directly (driving an infinite stream through an HTTP test transport is
unreliable); the route just wires it to the request's disconnect probe.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from amendia_auth import current_principal

from app.config import settings
from app.deps import get_hub
from app.hub import NotificationHub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Belt-and-suspenders against proxy buffering (nginx also sets proxy_buffering off).
    "X-Accel-Buffering": "no",
}


async def sse_stream(
    hub: NotificationHub,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_seconds: int,
) -> AsyncIterator[str]:
    """Yield SSE frames for one connected client until it disconnects."""
    q = hub.subscribe()
    logger.info("SSE client subscribed (subscribers=%d)", hub.subscriber_count)
    try:
        # Tell the client the stream is live → it flips status up + resyncs.
        yield "event: ready\ndata: {}\n\n"
        while True:
            if await is_disconnected():
                break
            try:
                signal = await asyncio.wait_for(q.get(), timeout=heartbeat_seconds)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(signal)}\n\n"
    finally:
        hub.unsubscribe(q)
        logger.info("SSE client unsubscribed (subscribers=%d)", hub.subscriber_count)


@router.get("/stream", dependencies=[Depends(current_principal)])
async def stream(request: Request, hub: NotificationHub = Depends(get_hub)) -> StreamingResponse:
    gen = sse_stream(hub, request.is_disconnected, settings.HEARTBEAT_SECONDS)
    return StreamingResponse(gen, media_type="text/event-stream", headers=_SSE_HEADERS)
