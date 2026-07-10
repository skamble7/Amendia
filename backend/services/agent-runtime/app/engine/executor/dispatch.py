# app/engine/executor/dispatch.py
"""Kind-dispatching in-process capability executor (``native`` mode).

  * ``skill`` — import ``runtime.entrypoint`` (``module:function``) and call it.
  * ``llm``   — simulation mode → the paired simulation skill (by capability_id);
                otherwise the real, provider-agnostic LLM path via polyllm +
                ConfigForge (see ``_execute_llm_real``).
  * ``mcp``   — simulation mode → the paired simulation skill; real path has no MCP
                client yet, so it falls back to the simulation skill with a warning
                (TODO(mcp): real MCP client).

Capabilities are pure/deterministic in simulation mode and return
``{"outputs": {artifact_key: data}, "log": str}`` or
``{"proposed_actions": [...], "log": str}``.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any, Callable, Dict, Optional

from amendia_contracts.capability import CapabilityDescriptor

from app.capabilities.wire_repair import SIM_CAPABILITIES
from app.config import settings
from app.engine.executor.base import CapabilityError, ExecutionContext

logger = logging.getLogger(__name__)

# One polyllm LLMClient per ConfigForge ref — the ModelProfile is fetched once and
# reused across capability invocations (the provider/model/keys live in ConfigForge).
_LLM_CLIENTS: Dict[str, Any] = {}


class InProcessExecutor:
    """Today's executor, unchanged — ``native`` mode. Implements the ``Executor`` protocol."""

    def execute(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        kind = descriptor.kind.value if hasattr(descriptor.kind, "value") else str(descriptor.kind)
        if kind == "skill":
            fn = self._resolve_skill(descriptor)
        elif kind == "llm":
            if ctx.simulation:
                fn = self._resolve_sim(descriptor)
            else:
                return self._execute_llm_real(descriptor, inputs, ctx)
        elif kind == "mcp":
            if ctx.simulation:
                fn = self._resolve_sim(descriptor)
            else:
                # No real MCP client yet. Until it lands, fall back to the paired
                # simulation skill so real-LLM runs still complete end-to-end.
                # TODO(mcp): replace with a real MCP client call.
                fn = SIM_CAPABILITIES.get(descriptor.capability_id)
                if fn is None:
                    raise NotImplementedError(
                        f"real MCP execution for {descriptor.capability_id} is not implemented "
                        "and no simulation fallback is registered"
                    )
                logger.warning(
                    "MCP capability %s has no real client yet — using simulation fallback",
                    descriptor.capability_id,
                )
        else:
            raise CapabilityError(f"unknown capability kind '{kind}' for {descriptor.capability_id}")

        try:
            result = fn(
                inputs=inputs,
                envelope=ctx.envelope,
                mode=ctx.mode,
                approved_action_ids=ctx.approved_action_ids,
            )
        except Exception as exc:  # noqa: BLE001
            raise CapabilityError(f"{descriptor.capability_id} raised: {exc}") from exc
        if not isinstance(result, dict):
            raise CapabilityError(f"{descriptor.capability_id} returned non-dict: {type(result)}")
        return result

    # ------------------------------------------------------------------ #
    def _resolve_skill(self, descriptor: CapabilityDescriptor) -> Callable:
        entrypoint = getattr(descriptor.runtime, "entrypoint", None)
        if not entrypoint or ":" not in entrypoint:
            raise CapabilityError(f"bad skill entrypoint for {descriptor.capability_id}: {entrypoint!r}")
        mod_path, fn_name = entrypoint.split(":", 1)
        try:
            mod = importlib.import_module(mod_path)
            return getattr(mod, fn_name)
        except (ImportError, AttributeError) as exc:
            raise CapabilityError(f"cannot import skill {entrypoint!r}: {exc}") from exc

    def _resolve_sim(self, descriptor: CapabilityDescriptor) -> Callable:
        fn = SIM_CAPABILITIES.get(descriptor.capability_id)
        if fn is None:
            raise CapabilityError(
                f"no simulation capability registered for {descriptor.capability_id}"
            )
        return fn

    # ------------------------------------------------------------------ #
    def _execute_llm_real(
        self, descriptor: CapabilityDescriptor, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        """Real LLM path (SIMULATION_MODE=false) — provider-agnostic via polyllm.

        The model, provider, keys and generation params live in ConfigForge; swapping
        vendors (OpenAI ↔ Gemini ↔ Claude-on-Bedrock) is a ConfigForge edit, not a code
        change. The config ref is chosen per the platform rule: **the capability's own
        declaration wins** (``descriptor.runtime.model_config_key``); when the capability
        declares nothing, we fall back to the runtime default (``settings.LLM_CONFIG_REF``).
        For each declared output artifact we prompt the model for a single JSON object
        constrained to the artifact's JSON Schema, then hand it back for schema validation.
        """
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


# --------------------------------------------------------------------------- #
# Reusable real-LLM primitive (shared by InProcessExecutor and the OpenShell fake).
# The provider/model/keys live in ConfigForge and are addressed by ``ref`` only — a
# reference, never a raw secret — so this can be routed through a managed inference
# proxy later (ADR-017 §6, Phase 2) without changing callers.
# --------------------------------------------------------------------------- #
def run_real_llm(
    *, capability_id: str, targets, ref: str, inputs: Dict[str, Any], envelope: Dict[str, Any]
):
    """Prompt the configured model for one schema-constrained JSON object per target.

    ``targets`` is a list of ``(artifact_key, json_schema_or_None)``. Returns
    ``(produced, provider, model)`` where ``produced`` maps artifact_key → parsed dict.
    """
    client = _llm_client(ref)
    produced: Dict[str, Any] = {}
    provider = model = None
    for artifact_key, schema in targets:
        schema_hint = (
            f"\n\nThe JSON object MUST validate against this JSON Schema:\n{json.dumps(schema)}"
            if schema else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are the '{capability_id}' capability in a payments "
                    f"exception-repair workflow. Produce a SINGLE JSON object for artifact "
                    f"'{artifact_key}'. Respond with JSON only — no markdown, no prose, no code "
                    f"fences.{schema_hint}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Payment exception envelope:\n{json.dumps(envelope, default=str)}\n\n"
                    f"Upstream artifacts (inputs):\n{json.dumps(inputs, default=str)}"
                ),
            },
        ]
        try:
            result = _run_blocking(client.chat(messages))
        except Exception as exc:  # noqa: BLE001 - surface as a capability failure
            raise CapabilityError(f"{capability_id}: LLM call failed: {exc}") from exc

        data = _parse_json(result.text)
        if data is None:
            raise CapabilityError(
                f"{capability_id}: LLM returned non-JSON for {artifact_key}: "
                f"{result.text[:200]!r}"
            )
        produced[artifact_key] = data
        provider = result.raw.get("provider")
        model = result.raw.get("model")
    return produced, provider, model


def _llm_client(ref: str) -> Any:
    """Fetch (and cache) a polyllm LLMClient for a given ConfigForge ref."""
    client = _LLM_CLIENTS.get(ref)
    if client is None:
        try:
            from polyllm import RemoteConfigLoader
        except ImportError as exc:  # pragma: no cover - real path only
            raise CapabilityError(
                "real LLM path requires polyllm — install the service's LLM dependencies "
                "(or set AGENTRT_SIMULATION_MODE=true)"
            ) from exc
        loader = RemoteConfigLoader(base_url=settings.CONFIG_FORGE_URL)
        client = _run_blocking(loader.load(ref))
        _LLM_CLIENTS[ref] = client
        logger.info("loaded LLM profile '%s' from ConfigForge (%s)", ref, settings.CONFIG_FORGE_URL)
    return client


# --------------------------------------------------------------------------- #
def _run_blocking(coro: Any) -> Any:
    """Run an async coroutine to completion from sync code.

    LangGraph nodes run in a worker thread (engine uses ``asyncio.to_thread``), so
    there is normally no running loop here and ``asyncio.run`` is safe. If a loop is
    somehow already running in this thread, isolate the coroutine on a fresh thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of a model response into a JSON object.

    polyllm already strips code fences for Bedrock ``json_mode``; this is a
    provider-agnostic safety net (fences / surrounding prose)."""
    text = (text or "").strip()
    if text.startswith("```"):
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("{"):
                text = part
                break
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            try:
                parsed = json.loads(text[i : j + 1])
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None
