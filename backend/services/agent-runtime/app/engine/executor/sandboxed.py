# app/engine/executor/sandboxed.py
"""SandboxedExecutor — capability execution via NemoClaw's OpenShell sandbox (ADR-017).

Implements the ``Executor`` protocol. For ``llm`` and ``mcp`` kinds it builds a
``CapabilityRunSpec`` and dispatches it to an ``OpenShellClient``, then hands the returned
artifacts back to the caller's **existing** ``_validate`` step (validation is not
duplicated here). For ``skill`` kinds in Phase 1 it delegates to the in-process executor —
side-effect-skill sandboxing is a later phase (§5, Phase 3) — logging that they ran
un-sandboxed so it's visible.

Invariants preserved: the host still owns every Mongo write and checkpoint; the sandbox
only returns artifact JSON (ADR-017 §8.1). The async client is called from the sync graph
node through the ADR-016 ``_run_blocking`` bridge, exactly like the real-LLM path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from amendia_contracts.capability import CapabilityDescriptor

from app.config import settings
from app.engine.executor.base import CapabilityError, ExecutionContext, Executor
from app.engine.executor.dispatch import InProcessExecutor, _run_blocking
from app.engine.executor.openshell import CapabilityRunSpec, OpenShellClient

logger = logging.getLogger(__name__)


def _kind(descriptor: CapabilityDescriptor) -> str:
    return descriptor.kind.value if hasattr(descriptor.kind, "value") else str(descriptor.kind)


class SandboxedExecutor:
    """``nemoclaw`` mode executor. Satisfies the ``Executor`` protocol."""

    def __init__(self, client: OpenShellClient, *, fallback: Optional[Executor] = None) -> None:
        self._client = client
        # skill kinds run un-sandboxed in Phase 1 (delegated to the in-process path).
        self._fallback: Executor = fallback or InProcessExecutor()
        # Phase 3/4: memoize deep_agent + review_after keyed on (element, inputs-hash) so a
        # HITL resume reuses the reviewed artifact instead of re-invoking the model (ADR-017
        # §8.2). Seam wired; a no-op in Phase 1.
        self._memo: Dict[str, Dict[str, Any]] = {}

    def execute(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        kind = _kind(descriptor)

        if kind == "skill":
            # Phase 3: side-effectful skills move into the sandbox with an egress allowlist +
            # brokered creds. Until then they run in-process — logged so it's auditable.
            logger.warning(
                "skill capability %s runs UN-SANDBOXED in Phase 1 (delegated to in-process "
                "executor); side-effect-skill sandboxing is ADR-017 Phase 3",
                descriptor.capability_id,
            )
            return self._fallback.execute(descriptor, inputs, ctx)

        if kind not in ("llm", "mcp"):
            raise CapabilityError(
                f"unknown capability kind '{kind}' for {descriptor.capability_id}"
            )

        spec = self._build_spec(descriptor, inputs, ctx, kind)
        # Phase 3/4: memoize here — self._memo.get((spec.element_id, inputs-hash)).
        try:
            result = _run_blocking(self._client.run_capability(spec))
        except CapabilityError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a capability failure
            raise CapabilityError(
                f"{descriptor.capability_id}: OpenShell sandbox execution failed: {exc}"
            ) from exc

        return self._assemble(spec, result)

    # ------------------------------------------------------------------ #
    def _build_spec(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any],
        ctx: ExecutionContext, kind: str,
    ) -> CapabilityRunSpec:
        # The selected model-config *ref* (never the key) — the platform rule from ADR-016:
        # the capability's own declaration wins; else the runtime default. Threaded so the
        # real client can later route it through the managed inference proxy (Phase 2).
        ref = None
        if kind == "llm":
            ref = getattr(descriptor.runtime, "model_config_key", None) or settings.LLM_CONFIG_REF
        output_schemas: Dict[str, Any] = (ctx.extras or {}).get("output_schemas", {})
        return CapabilityRunSpec(
            capability_id=descriptor.capability_id,
            kind=kind,
            inputs=inputs,
            envelope=ctx.envelope,
            output_schemas=output_schemas,
            mode=ctx.mode,
            approved_action_ids=ctx.approved_action_ids,
            model_config_ref=ref,
            element_id=(ctx.extras or {}).get("element_id"),
            simulation=ctx.simulation,
            # Phase 3: egress_policy derived from contract data (mcp.server_key, rail
            # endpoint, inference proxy). Placeholder handle in Phase 1.
            egress_policy=None,
        )

    def _assemble(self, spec: CapabilityRunSpec, result) -> Dict[str, Any]:
        prov = f"{result.provider}:{result.model}" if result.provider else "sandbox"
        ref = spec.model_config_ref or spec.kind
        # Log line consistent with ADR-016's "[<element>] real LLM [<ref>] (…) produced …",
        # with the sandbox trace appended (ADR-017 §8.1). task_runner emits it under [element].
        log = (
            f"real {spec.kind.upper()} [{ref}] ({prov}) produced "
            f"{', '.join(result.outputs) or '<none>'} via OpenShell sandbox "
            f"trace={result.otlp_trace_id}"
        )
        out: Dict[str, Any] = {
            "outputs": result.outputs,
            "log": log,
            # Threaded into the actor_log entry for this element (host-committed).
            "exec_meta": {
                "otlp_trace_id": result.otlp_trace_id,
                "provider": result.provider,
                "model": result.model,
                "via": "openshell",
            },
        }
        if result.proposed_actions is not None:
            out["proposed_actions"] = result.proposed_actions
        return out
