# app/engine/executor/base.py
"""Executor context, protocol, and error types.

The ``Executor`` protocol is the seam ADR-011 concentrated all capability dispatch
behind: a graph node gathers inputs and calls ``execute(descriptor, inputs, ctx)``,
then validates the returned outputs against the pinned schema. ADR-017 makes this an
explicit ``Protocol`` so an alternate substrate (``SandboxedExecutor``, the OpenShell
sandbox) can be swapped in without touching the pure/sync node code.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from amendia_contracts.capability import CapabilityDescriptor


class CapabilityError(Exception):
    """A capability failed to execute (bad descriptor, import error, runtime raise).

    This is a **technical** failure — the instance fails/retries (existing behaviour). Distinct from
    :class:`CapabilityBusinessError`, which is a *modeled* outcome routed to an error boundary."""


class CapabilityBusinessError(Exception):
    """ADR-030 (Phase 2.3): a capability signalled a **modeled business error** — a legitimate,
    diagram-anticipated outcome (payment rejected, screening hit, insufficient info), NOT a technical
    failure. The task runner routes it to the matching (or catch-all) BPMN error boundary event and
    the instance stays running. ``error_code`` matches a boundary's ``errorRef``/``<bpmn:error
    errorCode>``; ``detail`` is optional context. Any OTHER exception stays a technical failure."""

    def __init__(self, error_code: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self.error_code = error_code
        self.detail = detail or {}
        super().__init__(f"business error: {error_code}")


def _run_blocking(coro: Any) -> Any:
    """Run an async coroutine to completion from sync code (the ADR-016 sync↔async bridge).

    LangGraph nodes run in a worker thread (engine uses ``asyncio.to_thread``), so there is
    normally no running loop here and ``asyncio.run`` is safe. If a loop is somehow already
    running in this thread, isolate the coroutine on a fresh thread. Reused by the real-LLM
    path, the OpenShell clients, and the broker client (ADR-020) alike.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


@dataclass
class ExecutionContext:
    """Per-invocation context handed to the executor + capability.

    ``mode`` is ``propose`` (approve_actions pre-gate) or ``execute``.
    ``approved_action_ids`` narrows execution to a subset after a partial approval.
    ``extras`` threads the declared output JSON Schemas (``extras["output_schemas"]``)
    so the real LLM / sandbox paths can constrain generation to schema-valid artifacts.
    """

    envelope: Dict[str, Any]
    mode: str = "execute"
    approved_action_ids: Optional[List[str]] = None
    simulation: bool = True
    extras: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Executor(Protocol):
    """The capability-execution seam.

    Implementations: ``InProcessExecutor`` (``native`` mode, today's behaviour) and
    ``SandboxedExecutor`` (``nemoclaw`` mode, OpenShell). Both return the same shape —
    ``{"outputs": {artifact_key: data}, "log": str}`` or
    ``{"proposed_actions": [...], "log": str}`` — and may include an optional
    ``"exec_meta"`` dict (e.g. an OTLP trace id) that the task runner threads into the
    ``actor_log`` entry. The pinned-schema validation happens in the caller, unchanged.
    """

    def execute(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        ...
