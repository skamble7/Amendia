# app/logging_conf.py
"""Structured logging setup with request-id context (mirrors the other services)."""
from __future__ import annotations

import contextvars
import logging
import sys

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
exception_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("exception_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.exception_id = exception_id_ctx.get()
        return True


LOG_FORMAT = (
    "%(asctime)s level=%(levelname)s logger=%(name)s request_id=%(request_id)s "
    "exception_id=%(exception_id)s msg=%(message)s"
)

_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    root.addHandler(handler)
    _configured = True
