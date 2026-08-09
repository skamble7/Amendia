from __future__ import annotations

from typing import Any, Dict, List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from pega_stub.app import create_app
from pega_stub.orchestrator import Orchestrator


class FakeStore:
    """Records envelopes the orchestrator would POST to the trigger store; returns a fake trigger_id."""

    def __init__(self) -> None:
        self.submitted: List[Dict[str, Any]] = []

    async def submit(self, *, trigger_type: str, schema_version: str, payload: Dict[str, Any]) -> str:
        tid = f"trg-{len(self.submitted)}"
        self.submitted.append({"trigger_type": trigger_type, "schema_version": schema_version,
                               "payload": payload, "trigger_id": tid})
        return tid


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def orch(store: FakeStore) -> Orchestrator:
    return Orchestrator(submit=store.submit)


@pytest_asyncio.fixture
async def client(store: FakeStore, orch: Orchestrator):
    app = create_app()
    app.state.orchestrator = orch  # bypass lifespan (no live trigger store in tests)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
