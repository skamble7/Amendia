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
from app.engine.executor.memo import memoized_execute
from app.engine.executor.openshell import CapabilityRunSpec, OpenShellClient
from app.engine.executor.policy import derive_egress_policy

logger = logging.getLogger(__name__)


def _kind(descriptor: CapabilityDescriptor) -> str:
    return descriptor.kind.value if hasattr(descriptor.kind, "value") else str(descriptor.kind)


class SandboxedExecutor:
    """``nemoclaw`` mode executor. Satisfies the ``Executor`` protocol.

    Per-instance memoization (ADR-019) is applied here at executor entry and defaults **on**
    in ``nemoclaw`` mode: a HITL resume reuses the reviewed artifact instead of re-invoking
    the sandbox/model. The ``fallback`` (for ``skill`` kinds) is deliberately un-memoized so
    memoization is owned in exactly one place.
    """

    def __init__(self, client: OpenShellClient, *, fallback: Optional[Executor] = None,
                 memo: Optional[Any] = None, memoize: bool = True) -> None:
        self._client = client
        # skill kinds run un-sandboxed in Phase 1 (delegated to the in-process path).
        self._fallback: Executor = fallback or InProcessExecutor()
        self._memo = memo
        self._memoize = memoize and memo is not None

    def execute(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        # Memoization is MANDATORY for deep_agent (ADR-021 Part D): its output is
        # non-deterministic, so the reviewed artifact — not a fresh agent run — must commit on
        # resume. Fail closed if no memo store is wired.
        force_memo = _kind(descriptor) == "deep_agent"
        if force_memo and self._memo is None:
            raise CapabilityError(
                f"deep_agent '{descriptor.capability_id}' requires memoization but no memo "
                "store is configured (fail closed)"
            )
        return memoized_execute(
            memo=self._memo, enabled=(self._memoize or force_memo), inputs=inputs, ctx=ctx,
            run=lambda: self._execute_uncached(descriptor, inputs, ctx),
        )

    def _execute_uncached(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        kind = _kind(descriptor)
        if kind not in ("llm", "mcp", "skill", "deep_agent"):
            raise CapabilityError(
                f"unknown capability kind '{kind}' for {descriptor.capability_id}"
            )
        # ADR-020/021: ALL kinds run in the sandbox (the worker) — including side-effect skills
        # and deep_agent loops,
        # which execute under the creation-time egress allowlist (their action stays simulated
        # in dev). One path; the host still validates/commits/checkpoints/memoizes.
        spec = self._build_spec(descriptor, inputs, ctx, kind)
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
        extras = ctx.extras or {}
        constraints = getattr(descriptor, "constraints", None)
        timeout_s = getattr(constraints, "timeout_seconds", None) if constraints else None
        max_retries = (getattr(constraints, "max_retries", 0) if constraints else 0) or 0
        return CapabilityRunSpec(
            capability_id=descriptor.capability_id,
            kind=kind,
            inputs=inputs,
            envelope=ctx.envelope,
            output_schemas=output_schemas,
            error_codes=list(extras.get("error_codes") or []),  # ADR-035
            mode=ctx.mode,
            approved_action_ids=ctx.approved_action_ids,
            model_config_ref=ref,
            element_id=extras.get("element_id"),
            process_instance_id=extras.get("process_instance_id"),
            memo_attempt=int(extras.get("memo_attempt", 0) or 0),
            simulation=ctx.simulation,
            # Egress/tool policy derived from contract data (ADR-019 Part C): mcp.endpoint host +
            # tools whitelist, or the managed inference proxy host. Carried for auditability +
            # sandbox provisioning; the deterministic fake ignores it.
            egress_policy=derive_egress_policy(descriptor).to_dict(),
            # The worker needs the descriptor to run the shared core (ADR-020). Refs only.
            descriptor=descriptor,
            timeout_seconds=float(timeout_s) if timeout_s else None,
            max_retries=int(max_retries),
            idempotent=bool(getattr(descriptor, "idempotent", False)),
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
