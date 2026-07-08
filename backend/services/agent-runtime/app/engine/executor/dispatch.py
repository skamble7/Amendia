# app/engine/executor/dispatch.py
"""Kind-dispatching capability executor.

  * ``skill`` — import ``runtime.entrypoint`` (``module:function``) and call it.
  * ``llm``   — simulation mode → the paired simulation skill (by capability_id);
                otherwise a minimal real LangChain-Anthropic path (guarded so a
                missing API key only matters when simulation is off).
  * ``mcp``   — simulation mode → the paired simulation skill; real path raises
                ``NotImplementedError`` (future task).

Capabilities are pure/deterministic in simulation mode and return
``{"outputs": {artifact_key: data}, "log": str}`` or
``{"proposed_actions": [...], "log": str}``.
"""
from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Callable, Dict

from amendia_contracts.capability import CapabilityDescriptor

from app.capabilities.wire_repair import SIM_CAPABILITIES
from app.engine.executor.base import CapabilityError, ExecutionContext

logger = logging.getLogger(__name__)


class Executor:
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
                raise NotImplementedError(
                    f"real MCP execution for {descriptor.capability_id} is not implemented "
                    "(set AGENTRT_SIMULATION_MODE=true or implement the MCP client)"
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
        """Minimal real LLM path (only when AGENTRT_SIMULATION_MODE=false).

        Builds a JSON-producing prompt from the capability's declared output schema
        and calls Claude via langchain-anthropic, returning the structured artifact.
        Deliberately minimal — the simulation path is the tested one.
        """
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise CapabilityError(
                f"{descriptor.capability_id}: real LLM path requires ANTHROPIC_API_KEY "
                "(or set AGENTRT_SIMULATION_MODE=true)"
            )
        try:
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as exc:  # pragma: no cover - real path only
            raise CapabilityError(
                f"{descriptor.capability_id}: install the 'llm' extra (langchain-anthropic)"
            ) from exc

        out = descriptor.outputs[0]
        artifact_key = out.model_dump(by_alias=True)["schema"].split("@", 1)[0]
        model = ChatAnthropic(model="claude-sonnet-5", temperature=0)  # pragma: no cover
        sys = SystemMessage(content=(
            f"You are the '{descriptor.capability_id}' capability. Given the inputs, produce a "
            f"single JSON object conforming to artifact {artifact_key}. Respond with JSON only."
        ))
        human = HumanMessage(content=f"envelope={ctx.envelope}\ninputs={inputs}")
        import json as _json
        resp = model.invoke([sys, human])  # pragma: no cover
        data = _json.loads(resp.content if isinstance(resp.content, str) else resp.content[0]["text"])
        return {"outputs": {artifact_key: data}, "log": f"real LLM produced {artifact_key}"}
