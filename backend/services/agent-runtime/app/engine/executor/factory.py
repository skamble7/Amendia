# app/engine/executor/factory.py
"""Executor selection at engine-wiring time (ADR-017 Part E).

``build_executor(settings)`` returns the executor for the configured mode:
  * ``native``   → ``InProcessExecutor`` (today's path, byte-for-byte).
  * ``nemoclaw`` → ``SandboxedExecutor`` over an ``OpenShellClient``.

Fail-closed handling (ADR-017 §4.3): in ``nemoclaw`` mode we probe the gateway once. If it
is unreachable and ``NEMOCLAW_REQUIRED`` is true we raise ``NemoClawUnavailable`` (the
caller — lifespan — refuses to start); if false we degrade to ``native`` with a loud
warning. The deterministic ``FakeOpenShellClient`` (selected when ``OPENSHELL_URL`` is
unset) always reports reachable, so dev/CI exercises the sandboxed path with no gateway.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.engine.executor.base import Executor
from app.engine.executor.deep_agent import build_deep_agent_runner
from app.engine.executor.dispatch import InProcessExecutor, _run_blocking
from app.engine.executor.mcp_client import build_mcp_client
from app.engine.executor.memo import InMemoryMemoStore
from app.engine.executor.openshell import (
    BrokerOpenShellClient,
    FakeOpenShellClient,
    OpenShellClient,
    RabbitBrokerTransport,
)
from app.engine.executor.sandboxed import SandboxedExecutor
from app.engine.executor.stub_inference import SchemaStubDeepAgentRunner

logger = logging.getLogger(__name__)


def _capability_stack(settings) -> dict:
    """ADR-047 D2: the injectables every executor needs to run MCP-backed packs. Post-D2 there is NO
    per-process simulation code, so these must be wired for BOTH production and dev — the harness wires the
    same set via ``tests/_stub_stack``. Omitting them (the pre-D2 factory) makes every `mcp` capability fail
    closed on its first node.

      * ``mcp_client``  — always wired: an `mcp` capability has no fallback (``build_mcp_client`` returns the
        HTTP client that POSTs `tools/call` to the descriptor's self-descriptive endpoint, ADR-024).
      * ``stub_inference`` — under ``SIMULATION_MODE`` the `llm`/`deep_agent` kinds emit schema-valid stubs
        (no real provider); otherwise the real provider path runs.
      * ``deep_agent_runner`` — the schema-stub runner under simulation, else the configured real runner.
    """
    simulating = bool(getattr(settings, "SIMULATION_MODE", True))
    return {
        "mcp_client": build_mcp_client(settings),
        "stub_inference": simulating,
        "deep_agent_runner": SchemaStubDeepAgentRunner() if simulating else build_deep_agent_runner(settings),
    }


class NemoClawUnavailable(RuntimeError):
    """``nemoclaw`` mode required a reachable OpenShell gateway and none was available."""


def build_openshell_client(settings) -> OpenShellClient:
    """Select the OpenShell client (ADR-020):
      * ``AGENTRT_CAPABILITY_WORKER_ENABLED`` → ``BrokerOpenShellClient`` over RabbitMQ
        request/reply to the in-sandbox capability-worker (the real ``nemoclaw`` path);
      * otherwise → the deterministic ``FakeOpenShellClient`` (dev/CI default, no broker).

    (``HttpOpenShellClient`` is retired — OpenShell has no inbound execute API, ADR-019.)
    """
    if getattr(settings, "CAPABILITY_WORKER_ENABLED", False):
        logger.info("nemoclaw mode: BrokerOpenShellClient → capability-worker over RabbitMQ")
        return BrokerOpenShellClient(RabbitBrokerTransport(settings.RABBITMQ_URL))
    logger.info(
        "nemoclaw mode: capability-worker disabled — using deterministic FakeOpenShellClient"
    )
    # ADR-047 D2: the fake runs the SAME shared core as native (the spec carries the descriptor), so it needs
    # the SAME capability stack — else its delegated `mcp` calls fail closed exactly like the native path did.
    return FakeOpenShellClient(simulation=settings.SIMULATION_MODE, **_capability_stack(settings))


def build_executor(settings, *, client: Optional[OpenShellClient] = None,
                   memo: Optional[Any] = None) -> Executor:
    """Return the executor for ``settings.EXECUTION_MODE``.

    ``client`` and ``memo`` are injectable for tests. Memoization (ADR-019) is on by default in
    **both** ``native`` and ``nemoclaw`` modes (ADR-027 Phase 2.0) — the native path defaults a
    process-local store when none is injected, so the resume-replay hazard is closed out of the
    box. ``main.py`` injects the durable Mongo store; tests inject/get an in-memory one. Set
    ``AGENTRT_MEMOIZE_CAPABILITIES=false`` for byte-identical replay (no memoization).
    """
    mode = getattr(settings, "EXECUTION_MODE", "native")
    native_memoize = bool(getattr(settings, "MEMOIZE_CAPABILITIES", True))

    def _native() -> InProcessExecutor:
        # ADR-027 Phase 2.0: default a process-local memo store when memoization is on and none was
        # injected, so the resume-replay hazard is closed even if wiring is forgotten. `main.py`
        # injects the durable Mongo store; tests get InMemory. With memoize off → byte-identical.
        store = memo
        if native_memoize and store is None:
            store = InMemoryMemoStore()
        # ADR-047 D2: wire the capability stack (mcp_client / stub_inference / deep_agent_runner). Without it
        # every `mcp`-backed pack dies on its first node — the harness wired this but the factory did not.
        return InProcessExecutor(memo=store, memoize=native_memoize, **_capability_stack(settings))

    if mode == "native":
        return _native()
    if mode != "nemoclaw":
        raise ValueError(f"unknown AGENTRT_EXECUTION_MODE '{mode}' (expected native|nemoclaw)")

    client = client if client is not None else build_openshell_client(settings)
    if not _probe(client):
        if settings.NEMOCLAW_REQUIRED:
            raise NemoClawUnavailable(
                "OpenShell gateway unreachable and AGENTRT_NEMOCLAW_REQUIRED=true — refusing "
                "to start rather than run capabilities un-sandboxed (set false only in dev)"
            )
        logger.warning(
            "OpenShell gateway unreachable — degrading to native execution "
            "(AGENTRT_NEMOCLAW_REQUIRED=false)"
        )
        return _native()

    logger.info("execution mode: nemoclaw — SandboxedExecutor over %s", type(client).__name__)
    # nemoclaw defaults memoization on (effective only when a memo store is provided).
    return SandboxedExecutor(client, fallback=InProcessExecutor(), memo=memo, memoize=True)


def _probe(client: OpenShellClient) -> bool:
    """Sync bridge to the client's async reachability probe (never raises)."""
    try:
        return bool(_run_blocking(client.ping()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenShell gateway ping failed: %s", exc)
        return False
