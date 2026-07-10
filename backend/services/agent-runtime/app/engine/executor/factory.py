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
from typing import Optional

from app.engine.executor.base import Executor
from app.engine.executor.dispatch import InProcessExecutor, _run_blocking
from app.engine.executor.openshell import (
    FakeOpenShellClient,
    HttpOpenShellClient,
    OpenShellClient,
)
from app.engine.executor.sandboxed import SandboxedExecutor

logger = logging.getLogger(__name__)


class NemoClawUnavailable(RuntimeError):
    """``nemoclaw`` mode required a reachable OpenShell gateway and none was available."""


def build_openshell_client(settings) -> OpenShellClient:
    """Select the OpenShell client: the deterministic fake in dev/CI (no ``OPENSHELL_URL``),
    or the live HTTP scaffold when a gateway endpoint is configured."""
    if not settings.OPENSHELL_URL:
        logger.info(
            "nemoclaw mode: no AGENTRT_OPENSHELL_URL set — using deterministic "
            "FakeOpenShellClient (no live gateway)"
        )
        return FakeOpenShellClient(simulation=settings.SIMULATION_MODE)
    return HttpOpenShellClient(settings.OPENSHELL_URL, pool_size=settings.SANDBOX_POOL_SIZE)


def build_executor(settings, *, client: Optional[OpenShellClient] = None) -> Executor:
    """Return the executor for ``settings.EXECUTION_MODE``. ``client`` is injectable for tests."""
    mode = getattr(settings, "EXECUTION_MODE", "native")
    if mode == "native":
        return InProcessExecutor()
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
        return InProcessExecutor()

    logger.info("execution mode: nemoclaw — SandboxedExecutor over %s", type(client).__name__)
    return SandboxedExecutor(client, fallback=InProcessExecutor())


def _probe(client: OpenShellClient) -> bool:
    """Sync bridge to the client's async reachability probe (never raises)."""
    try:
        return bool(_run_blocking(client.ping()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenShell gateway ping failed: %s", exc)
        return False
