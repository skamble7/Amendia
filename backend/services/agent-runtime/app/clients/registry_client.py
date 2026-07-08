# app/clients/registry_client.py
"""HTTP client for the process-registry read APIs + the exception store fetch-back.

The runtime loads packs from the registry (never local collections): manifest,
pinned resolution, BPMN, capability descriptors, and artifact schemas.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class RegistryNotFound(Exception):
    """A registry resource returned 404 (unknown pack/capability/schema)."""


class RegistryError(Exception):
    """A registry call failed (5xx / network) after retries."""


class RegistryClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient, *, max_retries: int = 2) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._max_retries = max_retries

    async def _get(self, path: str, *, as_text: bool = False) -> Any:
        url = f"{self._base_url}{path}"
        last: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._http.get(url)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                logger.warning("registry GET %s network error (attempt %d): %s", path, attempt + 1, exc)
            else:
                if resp.status_code == 404:
                    raise RegistryNotFound(path)
                if resp.status_code >= 500:
                    last = RegistryError(f"{resp.status_code} for {path}")
                    logger.warning("registry GET %s → %s (attempt %d)", path, resp.status_code, attempt + 1)
                else:
                    resp.raise_for_status()
                    return resp.text if as_text else resp.json()
            if attempt < self._max_retries:
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RegistryError(str(last) if last else f"registry unreachable for {path}")

    async def get_pack(self, pack_key: str, version: str) -> Dict[str, Any]:
        return await self._get(f"/packs/{pack_key}/{version}")

    async def get_resolution(self, pack_key: str, version: str) -> Dict[str, Any]:
        return await self._get(f"/packs/{pack_key}/{version}/resolution")

    async def get_bpmn(self, pack_key: str, version: str) -> str:
        return await self._get(f"/packs/{pack_key}/{version}/bpmn", as_text=True)

    async def get_capability(self, capability_id: str, version: str) -> Dict[str, Any]:
        return await self._get(f"/capabilities/{capability_id}/{version}")

    async def get_artifact_schema(self, artifact_key: str, version: str) -> Dict[str, Any]:
        return await self._get(f"/artifact-schemas/{artifact_key}/{version}")


class ExceptionStoreClient:
    """Fetches the full exception envelope from the store's fetch-back URL."""

    def __init__(self, http: httpx.AsyncClient, *, max_retries: int = 2) -> None:
        self._http = http
        self._max_retries = max_retries

    async def fetch(self, fetch_url: str) -> Dict[str, Any]:
        last: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._http.get(fetch_url)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                last = exc
                logger.warning("envelope fetch %s failed (attempt %d): %s", fetch_url, attempt + 1, exc)
                if attempt < self._max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"envelope fetch failed after retries: {last}")
