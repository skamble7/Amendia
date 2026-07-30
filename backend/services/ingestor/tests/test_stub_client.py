# tests/test_stub_client.py
"""The fetch-back client is domain-neutral: it keeps the configured authority (SSRF-safe, host-portable) but
takes the PATH from the event's ``fetch_url`` so any pack's endpoint works (``/tickets/{id}`` as well as the
legacy ``/exceptions/{id}``)."""
import httpx
import pytest

from app.clients.stub_client import StubClient

pytestmark = pytest.mark.asyncio

_BASE = "http://stub:8085"


async def _capture(fetch_url):
    """GET via a StubClient over a mock transport; return the URL the client actually requested."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["internal"] = request.headers.get("X-Amendia-Internal")
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = StubClient(_BASE, http, internal_token="tok")
        body = await client.fetch_exception("TKT-123", fetch_url)
    assert body == {"ok": True}
    return seen


async def test_fetch_honors_event_path_keeping_configured_authority():
    # a dine-in ticket fetch-back — path from the event, authority from config.
    seen = await _capture("http://localhost:9999/tickets/TKT-123")
    assert seen["url"] == f"{_BASE}/tickets/TKT-123"
    assert seen["internal"] == "tok"


async def test_fetch_preserves_query_string():
    seen = await _capture("http://producer/tickets/TKT-123?view=full")
    assert seen["url"] == f"{_BASE}/tickets/TKT-123?view=full"


async def test_fetch_falls_back_to_legacy_path_when_fetch_url_empty():
    for missing in (None, "", "http://producer"):   # None / empty / pathless
        seen = await _capture(missing)
        assert seen["url"] == f"{_BASE}/exceptions/TKT-123"
