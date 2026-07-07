# app/clients/stub_client.py
"""HTTP client for the exception store (the stub) fetch-back API."""
from __future__ import annotations

from typing import Any, Dict

import httpx


class StubClient:
    """Fetches full exception documents from the store.

    The URL is built from a configured base (``STUB_BASE_URL``) rather than the
    event's ``fetch_url`` — the latter is ``localhost``-scoped and would not
    resolve from inside the compose network.
    """

    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    async def fetch_exception(self, exception_id: str) -> Dict[str, Any]:
        resp = await self._http.get(f"{self._base_url}/exceptions/{exception_id}")
        resp.raise_for_status()
        return resp.json()
