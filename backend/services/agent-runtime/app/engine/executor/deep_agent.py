# app/engine/executor/deep_agent.py
"""The `deep_agent` execution substrate (ADR-021).

A `DeepAgentRunner` runs a **bounded** Deep Agents Code loop inside the worker/sandbox and
must emit an object validating against the pinned output artifact schema (the host validates —
the contract boundary is the guarantee, design §9.2). The harness may use only the whitelisted
`tools`; model calls go to `inference.local/v1`; a hard step budget caps the loop.

Two implementations, mirroring the OpenShell-client pattern:
  * ``FakeDeepAgentRunner`` — deterministic, no model/agent loop; the **CI/dev default**. It
    produces a schema-valid artifact by reusing the paired simulation capability.
  * ``RealDeepAgentRunner`` — invokes the actual LangChain Deep Agents harness as an embedded
    bounded task. **Integration-gated** (needs the `deepagents` SDK + a model). Built against
    the *confirmed* surface (`create_deep_agent(model=, tools=, system_prompt=)` + `.invoke`);
    the structured-output param and MCP-tool passing are unconfirmed → prompt-and-host-validate
    fallback + `# [confirm]`, never an invented SDK surface.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Protocol

from app.capabilities.wire_repair import SIM_CAPABILITIES
from app.engine.executor.base import CapabilityError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Whitelisted read-only investigation tools (dev = stubs; sandbox = registry-brokered MCP).
# Docstrings + type hints are how Deep Agents derives tool schemas (confirmed).
# --------------------------------------------------------------------------- #
def fetch_attachment(attachment_id: str) -> dict:
    """Fetch a payment exception attachment's parsed contents by id (read-only)."""
    return {"attachment_id": attachment_id, "parsed": {"stub": True}}


def search_payment_history(account_id: str) -> dict:
    """Search prior settlement history for an account (read-only)."""
    return {"account_id": account_id, "prior_settlements": []}


def name_match(name_a: str, name_b: str) -> dict:
    """Fuzzy name-match two party names, returning a 0..1 score (read-only)."""
    score = 1.0 if name_a.strip().lower() == name_b.strip().lower() else 0.4
    return {"name_a": name_a, "name_b": name_b, "score": score}


_STUB_WORKER_TOOLS: Dict[str, Callable] = {
    "fetch_attachment": fetch_attachment,
    "search_payment_history": search_payment_history,
    "name_match": name_match,
}


def resolve_tools(tool_ids: List[str], *, mcp_client: Optional[Any] = None) -> List[Callable]:
    """Map whitelisted tool ids → callables. Worker functions are local; MCP tool ids resolve
    via the in-sandbox registry (ADR-020). Unknown ids fail closed — the registry already
    validated the whitelist, this is belt-and-suspenders."""
    resolved: List[Callable] = []
    for tid in tool_ids:
        if tid in _STUB_WORKER_TOOLS:
            resolved.append(_STUB_WORKER_TOOLS[tid])
        elif mcp_client is not None:
            # [confirm] how a registry-brokered MCP tool is wrapped as a deepagents tool.
            resolved.append(_mcp_tool_shim(tid, mcp_client))
        else:
            raise CapabilityError(f"deep_agent tool '{tid}' does not resolve on this path")
    return resolved


def _mcp_tool_shim(tool_id: str, mcp_client: Any) -> Callable:
    def _tool(**arguments) -> dict:  # pragma: no cover - real MCP path only
        from app.engine.executor.base import _run_blocking
        return _run_blocking(mcp_client.call_tool(
            server_key=None, tool=tool_id, arguments=arguments, transport="streamable_http"))
    _tool.__name__ = tool_id
    _tool.__doc__ = f"MCP tool '{tool_id}' (registry-brokered)."
    return _tool


# --------------------------------------------------------------------------- #
class DeepAgentRunner(Protocol):
    async def run(
        self, *, capability_id: str, prompt_key: str, input_artifacts: Dict[str, Any],
        tools: List[str], output_schema: Optional[dict], model_ref: Optional[str],
        budget: Any, envelope: Dict[str, Any], mcp_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run the bounded loop → a single structured artifact object (host-validated)."""
        ...


class FakeDeepAgentRunner:
    """Deterministic — the CI/dev default. Reuses the paired simulation capability to emit a
    schema-valid artifact (e.g. a `repair_verdict` with `evidence[]`) with no model/agent loop."""

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client=None):
        fn = SIM_CAPABILITIES.get(capability_id)
        if fn is None:
            raise CapabilityError(
                f"FakeDeepAgentRunner has no simulation for '{capability_id}' — register one in "
                "SIM_CAPABILITIES for the pilot, or use the real runner"
            )
        result = fn(inputs=input_artifacts, envelope=envelope, mode="execute", approved_action_ids=None)
        outputs = result.get("outputs", {}) or {}
        # deep_agent capabilities declare exactly one output artifact.
        return next(iter(outputs.values())) if outputs else {}


class RealDeepAgentRunner:
    """Invokes the real LangChain Deep Agents harness as a bounded embedded task. Integration-
    gated (needs the `deepagents` SDK + a reachable model). Confirmed surface only."""

    def __init__(self, *, inference_base_url: Optional[str] = None) -> None:
        self._inference_base_url = inference_base_url

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client=None):  # pragma: no cover - integration only
        try:
            from deepagents import create_deep_agent  # confirmed entrypoint
        except Exception as exc:  # noqa: BLE001
            raise CapabilityError(
                "RealDeepAgentRunner requires the deepagents SDK (present in the OpenShell "
                "sandbox). Use FakeDeepAgentRunner in dev/CI."
            ) from exc

        tool_fns = resolve_tools(tools, mcp_client=mcp_client)
        schema_hint = (
            f"\n\nYou MUST end by emitting a SINGLE JSON object (no prose, no fences) that "
            f"validates against this JSON Schema:\n{json.dumps(output_schema)}" if output_schema else ""
        )
        system_prompt = (
            f"You are the '{capability_id}' investigative capability in a payments exception "
            f"workflow. Task: {prompt_key}. Use ONLY the provided tools. Do not take any "
            f"side-effecting action.{schema_hint}"
        )
        # model_ref → inference.local/v1 (ADR-018/020). [confirm] the exact model= string form
        # the harness expects for an OpenAI-compatible managed proxy.
        model = f"openai:{model_ref}" if model_ref else "openai:nemotron-3-ultra"
        agent = create_deep_agent(model=model, tools=tool_fns, system_prompt=system_prompt)

        user = (
            f"Payment exception envelope:\n{json.dumps(envelope, default=str)}\n\n"
            f"Upstream artifacts:\n{json.dumps(input_artifacts, default=str)}"
        )
        # Bound the loop via the standard LangGraph recursion_limit (Deep Agents is a LangGraph
        # graph). [confirm] whether a token budget is separately configurable.
        max_steps = getattr(budget, "max_steps", 12) or 12
        from app.engine.executor.base import _run_blocking

        result = _run_blocking(_ainvoke(agent, user, max_steps))
        text = _final_text(result)
        data = _parse_json(text)
        if data is None:
            raise CapabilityError(
                f"{capability_id}: deep_agent returned non-JSON: {text[:200]!r}")
        return data


async def _ainvoke(agent, user, max_steps):  # pragma: no cover - integration only
    return await agent.ainvoke(
        {"messages": [{"role": "user", "content": user}]},
        config={"recursion_limit": max_steps},
    )


def _final_text(result: Any) -> str:  # pragma: no cover - integration only
    msgs = result.get("messages") if isinstance(result, dict) else None
    if msgs:
        last = msgs[-1]
        content = getattr(last, "content", None) or (last.get("content") if isinstance(last, dict) else None)
        if isinstance(content, str):
            return content
    return str(result)


def _parse_json(text: str) -> Optional[dict]:
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
    except Exception:  # noqa: BLE001
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except Exception:  # noqa: BLE001
                return None
        return None


def build_deep_agent_runner(settings) -> DeepAgentRunner:
    """Fake by default (CI/dev); real only when explicitly enabled (integration/sandbox)."""
    if getattr(settings, "DEEPAGENT_REAL", False):
        return RealDeepAgentRunner(inference_base_url=getattr(settings, "WORKER_INFERENCE_BASE_URL", None))
    return FakeDeepAgentRunner()
