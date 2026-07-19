# app/engine/executor/worker_runner.py
"""The capability-worker's execution logic (ADR-020): job dict → shared core → result dict.

Pure and broker-agnostic — reused by both the in-memory transport (host-side unit tests) and
the standalone ``capability-worker`` RabbitMQ consumer. It reconstructs the descriptor +
context from the job, runs the **shared execution core** (`executor/core.py`), and returns a
serializable result. It does **no** validation / checkpoint / memo / HITL — those stay
host-side (ADR-017 trap 2); the worker returns raw outputs only.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from amendia_contracts.capability import CapabilityDescriptor

from app.config import settings
from app.engine.executor.base import ExecutionContext
from app.engine.executor.core import execute_capability

logger = logging.getLogger(__name__)


def _emit_otlp_trace(spec: Dict[str, Any]) -> str:
    """Return an OTLP trace id for this execution. In an OpenShell sandbox the worker exports
    spans to ``settings.OTLP_ENDPOINT`` (host.openshell.internal:4318); in dev/CI export is a
    no-op and we just mint a correlatable id. # [confirm] OTLP span/exporter wiring in-sandbox.
    """
    rid = spec.get("_request_id") or spec.get("element_id") or spec.get("capability_id") or "x"
    return f"otlp-worker-{rid}-{uuid.uuid4().hex[:8]}"


def run_job(job: Dict[str, Any], *, mcp_client: Optional[Any] = None) -> Dict[str, Any]:
    """Execute one capability job. Never raises — failures are returned as ``ok: False`` so
    the host surfaces a clean node failure (never a swallowed error)."""
    request_id = job.get("request_id")
    spec = job.get("spec") or {}
    spec = {**spec, "_request_id": request_id}
    try:
        descriptor = CapabilityDescriptor.model_validate(spec["descriptor"])
        ctx = ExecutionContext(
            envelope=spec["envelope"],
            mode=spec.get("mode", "execute"),
            approved_action_ids=spec.get("approved_action_ids"),
            simulation=bool(spec.get("simulation", True)),
            extras={
                "output_schemas": spec.get("output_schemas", {}),
                "element_id": spec.get("element_id"),
                "process_instance_id": spec.get("process_instance_id"),
                "memo_attempt": spec.get("memo_attempt", 0),
                "error_codes": spec.get("error_codes", []),   # ADR-035
            },
        )
        kind = spec.get("kind")
        client = mcp_client
        if client is None and kind in ("mcp", "deep_agent") and not ctx.simulation:
            from app.engine.executor.mcp_client import build_mcp_client
            client = build_mcp_client(settings)
        runner = None
        if kind == "deep_agent":
            from app.engine.executor.deep_agent import build_deep_agent_runner
            runner = build_deep_agent_runner(settings)

        result = execute_capability(descriptor, spec.get("inputs", {}), ctx,
                                    mcp_client=client, deep_agent_runner=runner)

        return {
            "request_id": request_id,
            "ok": True,
            "result": {
                "outputs": result.get("outputs", {}) or {},
                "log": result.get("log"),
                "proposed_actions": result.get("proposed_actions"),
                "otlp_trace_id": _emit_otlp_trace(spec),
                "provider": None,
                "model": None,
            },
        }
    except Exception as exc:  # noqa: BLE001 - returned, not raised (host surfaces it)
        logger.warning("capability-worker job failed (request_id=%s): %s", request_id, exc)
        return {"request_id": request_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
