# app/clients/registry_client.py
"""HTTP client for the process-registry triage resolve API.

``resolve`` maps an envelope to a pinned pack. Three outcomes are distinguished
so the caller can drive the lifecycle:
  * match      → returns the ``ResolveResponse`` dict.
  * no match   → raises ``RegistryNoMatch`` (HTTP 404) — terminal ``no_process``.
  * unreachable→ raises ``RegistryUnavailable`` after retries — stay ``received``,
                 the retry sweep re-attempts later.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


class RegistryNoMatch(Exception):
    """The registry has no active pack for this exception (HTTP 404)."""

    def __init__(self, body: Dict[str, Any]) -> None:
        self.body = body
        super().__init__(body.get("detail", "no active pack matched"))


class RegistryUnavailable(Exception):
    """The registry could not be reached / returned 5xx after all retries."""


class RegistryClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient, *, max_retries: int = 2) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._max_retries = max_retries

    async def resolve(self, tenant: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """POST /resolve. Retries on 5xx/network; raises on 404 / exhaustion."""
        url = f"{self._base_url}/resolve"
        payload = {"tenant": tenant, "envelope": envelope}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._http.post(url, json=payload)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("registry resolve network error (attempt %d): %s", attempt + 1, exc)
            else:
                if resp.status_code == 404:
                    raise RegistryNoMatch(_safe_json(resp))
                if resp.status_code >= 500:
                    last_exc = RegistryUnavailable(f"registry {resp.status_code}")
                    logger.warning("registry resolve 5xx (attempt %d): %s", attempt + 1, resp.status_code)
                else:
                    resp.raise_for_status()
                    return resp.json()
            if attempt < self._max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RegistryUnavailable(str(last_exc) if last_exc else "registry unreachable")


def _safe_json(resp: httpx.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"detail": resp.text}
