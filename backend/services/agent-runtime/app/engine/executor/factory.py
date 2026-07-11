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
from app.engine.executor.dispatch import InProcessExecutor, _run_blocking
from app.engine.executor.openshell import (
    BrokerOpenShellClient,
    FakeOpenShellClient,
    OpenShellClient,
    RabbitBrokerTransport,
)
from app.engine.executor.sandboxed import SandboxedExecutor

logger = logging.getLogger(__name__)


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
    return FakeOpenShellClient(simulation=settings.SIMULATION_MODE)


def build_executor(settings, *, client: Optional[OpenShellClient] = None,
                   memo: Optional[Any] = None) -> Executor:
    """Return the executor for ``settings.EXECUTION_MODE``.

    ``client`` and ``memo`` are injectable for tests. Memoization (ADR-019) is enabled by
    default in ``nemoclaw`` mode and, in ``native`` mode, when
    ``AGENTRT_MEMOIZE_CAPABILITIES`` is set — but only takes effect when a ``memo`` store is
    provided (``main.py`` wires the Mongo store; tests inject an in-memory one). With no
    store, ``native`` stays byte-for-byte.
    """
    mode = getattr(settings, "EXECUTION_MODE", "native")
    native_memoize = bool(getattr(settings, "MEMOIZE_CAPABILITIES", False))
    if mode == "native":
        return InProcessExecutor(memo=memo, memoize=native_memoize)
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
        return InProcessExecutor(memo=memo, memoize=native_memoize)

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
