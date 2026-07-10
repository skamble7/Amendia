# app/middleware/request_id.py
"""Request-ID middleware — **pure ASGI** (deliberately not BaseHTTPMiddleware).

BaseHTTPMiddleware buffers the response body, which breaks long-lived SSE streams
(events never flush until the response ends). A pure-ASGI middleware only wraps the
``send`` callable to stamp the response header and binds the logging context — it
never touches the streamed body — so the SSE endpoint flushes normally.
"""
from __future__ import annotations

import uuid

from app.logging_conf import request_id_ctx

HEADER = b"x-request-id"


class RequestIDMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for k, v in scope.get("headers", []):
            if k == HEADER:
                incoming = v.decode("latin-1")
                break
        request_id = incoming or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((HEADER, request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)
