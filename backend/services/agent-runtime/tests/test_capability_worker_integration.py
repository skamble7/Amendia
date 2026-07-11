# tests/test_capability_worker_integration.py
"""ADR-020 — env-gated integration tests for the REAL broker path.

Skipped by default (CI runs on the in-memory transport). Enable with
``AGENTRT_OPENSHELL_IT=1`` and a running RabbitMQ + a ``capability-worker``
(``python -m worker.main``) and a stub MCP server. These exercise
``RabbitBrokerTransport`` end-to-end without OpenShell (the worker is a plain process).
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.executor.openshell import (
    BrokerOpenShellClient,
    CapabilityRunSpec,
    RabbitBrokerTransport,
)
from tests._wire import make_envelope

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not settings.OPENSHELL_IT, reason="set AGENTRT_OPENSHELL_IT=1 + run worker"),
]


@pytest.mark.asyncio
async def test_real_broker_ping():
    transport = RabbitBrokerTransport(settings.RABBITMQ_URL)
    assert await transport.ping() is True


@pytest.mark.asyncio
async def test_real_broker_roundtrip_sanctions():
    b = PackBundle.from_seed_dir(settings.SEED_DIR)
    d = b.descriptors["cap.payment.sanctions_screen"]
    spec = CapabilityRunSpec(
        capability_id=d.capability_id, kind="mcp", inputs={}, envelope=make_envelope("AC01"),
        element_id="Task_SanctionsRescreen", process_instance_id="pi-it-1",
        simulation=True, descriptor=d, timeout_seconds=30,
    )
    client = BrokerOpenShellClient(RabbitBrokerTransport(settings.RABBITMQ_URL))
    res = await asyncio.wait_for(client.run_capability(spec), timeout=35)
    assert res.outputs["art.compliance.screening_result"]["verdict"] in ("clean", "hit")
    assert res.otlp_trace_id
