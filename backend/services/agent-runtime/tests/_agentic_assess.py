# tests/_agentic_assess.py
"""Domain CI stub for wire-repair-agentic's deep_agent Assess.

`wire-repair-standard` terminates the needs-info loop because its Assess is an MCP tool whose (domain) stub maps
``resolution → verdict`` deterministically. `wire-repair-agentic`'s Assess is a `deep_agent` whose verdict is
produced by a real LLM — so in production the mapping lives in the capability's registered prompt. In CI the real
agent doesn't run; the platform default (``SchemaStubDeepAgentRunner``) emits the first enum value (``repairable``)
and ignores inputs, so a needs-info exception would never even enter the loop and a test would be green-but-
unverified.

This runner is the CI analog of standard's MCP stub: for the agentic Assess capability it REUSES the exact
standard ``assess_beneficiary`` handler (same reason-code + resolution → verdict mapping), so agentic honors
identical semantics and the integration test exercises real termination. It lives in the fixture layer — NOT the
platform — exactly like ``mcp_stub`` does for standard; every other deep_agent capability delegates to the
domain-neutral schema stub.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.engine.executor.stub_inference import SchemaStubDeepAgentRunner
from tests._mcp_server_tools import server_tool_map

_ASSESS_CAP = "cap.payment.assess_beneficiary_agentic"


class WireAgenticDeepAgentRunner:
    """Deep-agent CI runner that gives the agentic Assess the SAME verdict semantics as standard's MCP stub."""

    def __init__(self) -> None:
        self._fallback = SchemaStubDeepAgentRunner()
        self._assess = server_tool_map()["assess_beneficiary"]

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client: Optional[Any] = None,
                  title=None, description=None) -> Dict[str, Any]:
        if capability_id == _ASSESS_CAP:
            # The analyst's Obtain-Info disposition (whole artifact or None on the first pass) + the trigger's
            # reason codes — the inputs the standard handler keys off. Reusing it guarantees identical mapping.
            res = (input_artifacts or {}).get("info_resolution")
            outcome = res.get("outcome") if isinstance(res, dict) else None
            args = {"reason_codes": (envelope or {}).get("reason_codes") or [], "resolution": outcome}
            return self._assess(args)
        return await self._fallback.run(
            capability_id=capability_id, prompt_key=prompt_key, input_artifacts=input_artifacts,
            tools=tools, output_schema=output_schema, model_ref=model_ref, budget=budget,
            envelope=envelope, mcp_client=mcp_client, title=title, description=description)
