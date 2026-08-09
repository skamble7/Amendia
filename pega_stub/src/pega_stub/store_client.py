# src/pega_stub/store_client.py
"""Thin HTTP client that injects an envelope into the trigger store (POST /triggers).

The Pega stub never talks to RabbitMQ or fetches back — it only submits envelopes over HTTP and receives
handbacks. The store persists + publishes the TriggerRaisedEvent; the ingestor takes it from there.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


class StoreClient:
    def __init__(self, base_url: str, *, internal_token: str = "", source: str = "pega") -> None:
        self._base = base_url.rstrip("/")
        self._source = source
        self._headers = {"X-Amendia-Internal": internal_token} if internal_token else {}

    async def submit(self, *, trigger_type: str, schema_version: str, payload: Dict[str, Any]) -> str:
        """POST an envelope into the store; returns the assigned trigger_id. Raises on transport/HTTP error."""
        body = {"trigger_type": trigger_type, "schema_version": schema_version,
                "source": self._source, "payload": payload}
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(f"{self._base}/triggers", json=body, headers=self._headers)
            resp.raise_for_status()
            trigger_id = resp.json()["trigger"]["trigger_id"]
        logger.info("submitted %s → trigger_id=%s (case=%s)", trigger_type, trigger_id, payload.get("case_id"))
        return trigger_id
