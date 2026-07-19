"""Capability executor seam.

``native`` mode → ``InProcessExecutor`` (kind-dispatch skill/llm/mcp with a simulation
seam, unchanged from ADR-011/016). ``nemoclaw`` mode → ``SandboxedExecutor`` (routes
``llm``/``mcp`` execution through NemoClaw's OpenShell sandbox, ADR-017). ``build_executor``
selects between them at engine-wiring time from ``settings.EXECUTION_MODE``.
"""
from app.engine.executor.base import (
    CancellationToken,
    CapabilityBusinessError,
    CapabilityError,
    ExecutionContext,
    Executor,
    business_error_from_object,
)
from app.engine.executor.dispatch import InProcessExecutor
from app.engine.executor.factory import NemoClawUnavailable, build_executor
from app.engine.executor.sandboxed import SandboxedExecutor

__all__ = [
    "CapabilityBusinessError",
    "CapabilityError",
    "ExecutionContext",
    "Executor",
    "InProcessExecutor",
    "SandboxedExecutor",
    "build_executor",
    "NemoClawUnavailable",
    "business_error_from_object",
    "CancellationToken",
]
