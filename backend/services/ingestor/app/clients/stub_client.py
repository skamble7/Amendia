# app/clients/stub_client.py
"""HTTP client for the trigger store (the stub) fetch-back API."""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx


class StubClient:
    """Fetches full trigger documents from the store.

    The **authority** (scheme/host/port) is always the configured base (``STUB_BASE_URL``), never the event's:
    the event's ``fetch_url`` is producer-scoped (typically ``localhost``) and would not resolve — nor be
    trustworthy — from inside the compose network (SSRF-safe, host-portable). The **path** is taken from the
    event's ``fetch_url`` so any pack's fetch-back endpoint works (``/exceptions/{id}``, ``/tickets/{id}``, …)
    — domain-neutral. Falls back to the legacy ``/exceptions/{id}`` when no usable path is supplied.
    """

    def __init__(self, base_url: str, http: httpx.AsyncClient, *, internal_token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        # Fetch-back is a service-to-service call; carry the shared internal token.
        self._headers = {"X-Amendia-Internal": internal_token} if internal_token else {}

    async def fetch_exception(self, exception_id: str, fetch_url: Optional[str] = None) -> Dict[str, Any]:
        parts = urlsplit(fetch_url or "")
        path = parts.path if parts.path else f"/exceptions/{exception_id}"
        target = f"{self._base_url}{path}"
        if parts.query:
            target = f"{target}?{parts.query}"
        resp = await self._http.get(target, headers=self._headers)
        resp.raise_for_status()
        return resp.json()
