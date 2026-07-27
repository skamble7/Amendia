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

from app.engine.executor.base import CapabilityError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# A deep_agent's whitelisted tools are MCP tools (ADR-047 D2): the investigative helpers live on the MCP
# server, resolved via the registry-brokered MCP client — the platform carries no in-code tool.
# --------------------------------------------------------------------------- #
def resolve_tools(tool_ids: List[str], *, mcp_client: Optional[Any] = None) -> List[Callable]:
    """Map whitelisted tool ids → callables. Every tool is an MCP tool resolved via the in-sandbox
    registry-brokered client (ADR-020/D2); with no client an id fails closed."""
    if mcp_client is None:
        raise CapabilityError(
            f"deep_agent tools {tool_ids} require an MCP client (none on this path)")
    return [_mcp_tool_shim(tid, mcp_client) for tid in tool_ids]


def _mcp_tool_shim(tool_id: str, mcp_client: Any, *, endpoint: Optional[str] = None) -> Callable:
    def _tool(**arguments) -> dict:  # pragma: no cover - real MCP path only
        from app.engine.executor.base import _run_blocking
        # [confirm] a deep_agent MCP tool's endpoint would come from the whitelisted tool's
        # own descriptor/config (ADR-024 self-descriptive) — threaded here when that lands.
        return _run_blocking(mcp_client.call_tool(
            endpoint=endpoint, tool=tool_id, arguments=arguments, transport="streamable_http"))
    _tool.__name__ = tool_id
    _tool.__doc__ = f"MCP tool '{tool_id}' (self-descriptive endpoint)."
    return _tool


def build_system_prompt(capability_id: str, title: Optional[str], description: Optional[str],
                        prompt_key: str, schema_hint: str = "") -> str:
    """The deep-agent system prompt — **descriptor-framed** (ADR-047), mirroring ``run_real_llm``.

    ``title``/``description`` come from the capability's registered descriptor and are the ONLY channel that
    carries its behavioural rules to the live model (``prompt_key`` has no resolvable text today), so both are
    embedded verbatim when present. Domain-neutral: the platform adds no business nouns of its own."""
    role = f" — {title}" if title else ""
    role_desc = f" {description}" if description else ""
    return (
        f"You are the '{capability_id}' capability{role}.{role_desc} Task: {prompt_key}. Use ONLY the provided "
        f"tools. Do not take any side-effecting action.{schema_hint}"
    )


# --------------------------------------------------------------------------- #
class DeepAgentRunner(Protocol):
    async def run(
        self, *, capability_id: str, prompt_key: str, input_artifacts: Dict[str, Any],
        tools: List[str], output_schema: Optional[dict], model_ref: Optional[str],
        budget: Any, envelope: Dict[str, Any], mcp_client: Optional[Any] = None,
        title: Optional[str] = None, description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the bounded loop → a single structured artifact object (host-validated). ``title``/``description``
        are the capability's descriptor framing (ADR-047) — the domain-neutral channel for its instructions."""
        ...


class FakeDeepAgentRunner:
    """Deterministic — the CI/dev default (ADR-047 D2). Emits a minimal **schema-valid** artifact straight
    from the pinned output schema (domain-neutral, no `SIM_CAPABILITIES`, no model/agent loop)."""

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client=None, title=None, description=None):
        from app.engine.executor.stub_inference import stub_from_schema
        return stub_from_schema(output_schema or {})


class RealDeepAgentRunner:
    """Invokes the real LangChain Deep Agents harness as a bounded embedded task. Integration-
    gated (needs the `deepagents` SDK + a reachable model). Confirmed surface only."""

    def __init__(self, *, inference_base_url: Optional[str] = None) -> None:
        self._inference_base_url = inference_base_url

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client=None,
                  title=None, description=None):  # pragma: no cover - integration only
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
        # ADR-047: domain-neutral framing — the capability's role/task/instructions come from its registered
        # descriptor (title/description), NOT a hardcoded business area. This mirrors run_real_llm so a deep_agent
        # is instructed the same way an llm capability is; the description is the channel that carries a
        # capability's behavioural rules (e.g. the resolution→verdict mapping) to the live model. ``prompt_key``
        # stays a bare task label until a real prompt store resolves it (out of scope).
        system_prompt = build_system_prompt(capability_id, title, description, prompt_key, schema_hint)
        # model_ref → inference.local/v1 (ADR-018/020). [confirm] the exact model= string form
        # the harness expects for an OpenAI-compatible managed proxy.
        model = f"openai:{model_ref}" if model_ref else "openai:nemotron-3-ultra"
        agent = create_deep_agent(model=model, tools=tool_fns, system_prompt=system_prompt)

        user = (
            f"Trigger:\n{json.dumps(envelope, default=str)}\n\n"
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
