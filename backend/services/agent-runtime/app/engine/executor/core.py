# app/engine/executor/core.py
"""The shared capability-execution core (ADR-020).

One implementation of kind-dispatch (``skill`` / ``llm`` / ``mcp``) used by **both** the
in-process path (`InProcessExecutor`, ``native`` mode) and the in-sandbox
`capability-worker` (``nemoclaw`` mode over the broker). Keeping a single core means the two
paths are behaviourally identical by construction.

It returns the raw capability result dict — ``{"outputs": {...}, "log": str}`` or
``{"proposed_actions": [...], "log": str}`` — and performs **no** validation, checkpointing,
HITL, or memo work: those stay host-side (ADR-017 trap 2). An optional ``mcp_client`` enables
real MCP execution (the worker supplies one; in-process passes ``None`` → the simulation
fallback, preserving native behaviour).
"""
from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Callable, Dict, Optional

from amendia_contracts.capability import CapabilityDescriptor

from app.capabilities.wire_repair import SIM_CAPABILITIES
from app.config import settings
from app.engine.executor.base import CapabilityBusinessError, CapabilityError, ExecutionContext

logger = logging.getLogger(__name__)


def _kind(descriptor: CapabilityDescriptor) -> str:
    return descriptor.kind.value if hasattr(descriptor.kind, "value") else str(descriptor.kind)


def _resolve_skill(descriptor: CapabilityDescriptor) -> Callable:
    entrypoint = getattr(descriptor.runtime, "entrypoint", None)
    if not entrypoint or ":" not in entrypoint:
        raise CapabilityError(f"bad skill entrypoint for {descriptor.capability_id}: {entrypoint!r}")
    mod_path, fn_name = entrypoint.split(":", 1)
    try:
        mod = importlib.import_module(mod_path)
        return getattr(mod, fn_name)
    except (ImportError, AttributeError) as exc:
        raise CapabilityError(f"cannot import skill {entrypoint!r}: {exc}") from exc


def _resolve_sim(descriptor: CapabilityDescriptor) -> Callable:
    fn = SIM_CAPABILITIES.get(descriptor.capability_id)
    if fn is None:
        raise CapabilityError(f"no simulation capability registered for {descriptor.capability_id}")
    return fn


def _call(fn: Callable, descriptor: CapabilityDescriptor, inputs, ctx: ExecutionContext) -> Dict[str, Any]:
    try:
        result = fn(
            inputs=inputs, envelope=ctx.envelope, mode=ctx.mode,
            approved_action_ids=ctx.approved_action_ids,
        )
    except CapabilityBusinessError:
        # ADR-030: a modeled business error is NOT a technical failure — let it propagate so the
        # task runner can route it to the error boundary rather than wrapping it as a CapabilityError.
        raise
    except Exception as exc:  # noqa: BLE001
        raise CapabilityError(f"{descriptor.capability_id} raised: {exc}") from exc
    if not isinstance(result, dict):
        raise CapabilityError(f"{descriptor.capability_id} returned non-dict: {type(result)}")
    return result


def execute_capability(
    descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext,
    *, mcp_client: Optional[Any] = None, deep_agent_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Kind-dispatch one capability. Pure w.r.t. host state (no validate/commit/memo)."""
    kind = _kind(descriptor)

    if kind == "skill":
        return _call(_resolve_skill(descriptor), descriptor, inputs, ctx)

    if kind == "deep_agent":
        # nemoclaw-only: a deep_agent runner is only supplied on the worker/sandbox path. Its
        # absence here (e.g. native in-process) is a fail-closed refusal (ADR-021 Part D).
        if deep_agent_runner is None:
            raise CapabilityError(
                f"deep_agent capability '{descriptor.capability_id}' requires nemoclaw mode "
                "(no deep_agent runner on this execution path)"
            )
        return _execute_deep_agent(descriptor, inputs, ctx, deep_agent_runner, mcp_client)

    if kind == "llm":
        if ctx.simulation:
            return _call(_resolve_sim(descriptor), descriptor, inputs, ctx)
        return _execute_llm_real(descriptor, inputs, ctx)

    if kind == "mcp":
        if ctx.simulation:
            return _call(_resolve_sim(descriptor), descriptor, inputs, ctx)
        if mcp_client is not None:
            # Real MCP transport (worker path, ADR-020 Part D; ADR-024). endpoint/tools/
            # transport/headers come straight from the self-descriptive descriptor; the client
            # POSTs tools/call to that endpoint. list_provider stays stub in dev (no real OFAC).
            return _execute_mcp_real(descriptor, inputs, ctx, mcp_client)
        # No MCP client (native / fake) → paired simulation skill. Boundary logged.
        fn = SIM_CAPABILITIES.get(descriptor.capability_id)
        if fn is None:
            raise NotImplementedError(
                f"real MCP execution for {descriptor.capability_id} is not available and no "
                "simulation fallback is registered"
            )
        logger.warning(
            "MCP capability %s: no MCP client on this path — using simulation fallback",
            descriptor.capability_id,
        )
        return _call(fn, descriptor, inputs, ctx)

    raise CapabilityError(f"unknown capability kind '{kind}' for {descriptor.capability_id}")


# --------------------------------------------------------------------------- #
def _execute_llm_real(descriptor, inputs, ctx: ExecutionContext) -> Dict[str, Any]:
    """Real LLM path — provider-agnostic via polyllm/ConfigForge. In the worker the selected
    ``nemoclaw`` ref routes to ``inference.local/v1`` (ADR-018); creds are brokered by
    OpenShell, so no raw key is held here."""
    from app.engine.executor.dispatch import run_real_llm  # lazy — avoids import cycle

    ref = getattr(descriptor.runtime, "model_config_key", None) or settings.LLM_CONFIG_REF
    output_schemas: Dict[str, Any] = (ctx.extras or {}).get("output_schemas", {})
    targets = [
        (akey, output_schemas.get(akey))
        for akey in (
            out.model_dump(by_alias=True)["schema"].split("@", 1)[0]
            for out in descriptor.outputs
        )
    ]
    produced, provider, model = run_real_llm(
        capability_id=descriptor.capability_id, targets=targets, ref=ref,
        inputs=inputs, envelope=ctx.envelope,
    )
    return {
        "outputs": produced,
        "log": f"real LLM [{ref}] ({provider}:{model}) produced {', '.join(produced)}",
    }


def _execute_deep_agent(descriptor, inputs, ctx: ExecutionContext, runner, mcp_client) -> Dict[str, Any]:
    """Run a bounded Deep Agents loop → one schema-valid artifact (ADR-021). The host still
    validates against the pinned schema and commits/checkpoints/memoizes."""
    from app.config import settings
    from app.engine.executor.base import _run_blocking

    rt = descriptor.runtime
    artifact_key = descriptor.outputs[0].model_dump(by_alias=True)["schema"].split("@", 1)[0]
    output_schema = (ctx.extras or {}).get("output_schemas", {}).get(artifact_key)
    ref = getattr(rt, "model_config_key", None) or settings.LLM_CONFIG_REF
    try:
        artifact = _run_blocking(runner.run(
            capability_id=descriptor.capability_id,
            prompt_key=getattr(rt, "prompt_key", ""),
            input_artifacts=inputs,
            tools=list(getattr(rt, "tools", []) or []),
            output_schema=output_schema,
            model_ref=ref,
            budget=getattr(rt, "budget", None),
            envelope=ctx.envelope,
            mcp_client=mcp_client,
        ))
    except CapabilityError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CapabilityError(f"{descriptor.capability_id}: deep_agent run failed: {exc}") from exc
    return {
        "outputs": {artifact_key: artifact},
        "log": f"deep_agent [{ref}] tools={list(getattr(rt, 'tools', []) or [])} produced {artifact_key}",
    }


def _execute_mcp_real(descriptor, inputs, ctx: ExecutionContext, mcp_client) -> Dict[str, Any]:
    """Real MCP path (ADR-020 Part D; ADR-024): broker the capability's tool call through the
    MCP client, which POSTs `tools/call` to the descriptor's self-descriptive ``endpoint`` over
    the declared transport, and map the result into the declared artifact. The host validates it."""
    from app.engine.executor.base import _run_blocking

    rt = descriptor.runtime
    endpoint = getattr(rt, "endpoint", None)
    tools = list(getattr(rt, "tools", []) or [])
    transport = getattr(rt, "transport", None)
    transport = transport.value if hasattr(transport, "value") else (str(transport) if transport else None)
    headers = dict(getattr(rt, "headers", {}) or {})
    tool = tools[0] if tools else None
    if not endpoint or not tool:
        raise CapabilityError(f"{descriptor.capability_id}: mcp runtime missing endpoint/tools")

    # Arguments derived from the pinned envelope/inputs — the party to screen. list_provider
    # stays stub in dev (no real OFAC); the MCP *transport* is what's real here.
    arguments = {"envelope": ctx.envelope, "inputs": inputs}
    try:
        artifact = _run_blocking(mcp_client.call_tool(
            endpoint=endpoint, tool=tool, arguments=arguments, transport=transport, headers=headers,
        ))
    except Exception as exc:  # noqa: BLE001
        raise CapabilityError(f"{descriptor.capability_id}: MCP call failed: {exc}") from exc

    artifact_key = descriptor.outputs[0].model_dump(by_alias=True)["schema"].split("@", 1)[0]
    return {
        "outputs": {artifact_key: artifact},
        "log": f"real MCP [{endpoint}:{tool}] produced {artifact_key}",
    }
