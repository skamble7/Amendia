# app/engine/executor/stub_inference.py
"""ADR-047 D2 — a domain-neutral, `SIM_CAPABILITIES`-free fake for `llm` / `deep_agent` capabilities.

In production these kinds hit a real model / nemoclaw runner (descriptor-driven). In dev/CI we need a
deterministic stand-in that doesn't depend on any per-process simulation code (which D2 deletes). This module
generates a **minimal schema-valid artifact instance** straight from the pinned output JSON Schema — generic
morphology only, no capability-specific knowledge — and a matching deep_agent runner. The content is a
placeholder; the *shape* is contract-valid, which is exactly what an outcome-equivalence (name/route-based)
run needs, and what keeps the host's output validation happy.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def stub_from_schema(schema: Any) -> Any:
    """A minimal instance that validates against ``schema`` (draft 2020-12 subset). Honors const/enum,
    required object properties (recursively), array ``minItems``, and scalar defaults."""
    if not isinstance(schema, dict):
        return None
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type")
    if isinstance(t, list):                                   # nullable union → first non-null type
        t = next((x for x in t if x != "null"), t[0] if t else None)
    if t == "object" or (t is None and "properties" in schema):
        props = schema.get("properties", {}) or {}
        required = schema.get("required") or list(props)
        return {k: (stub_from_schema(props[k]) if k in props else None) for k in required}
    if t == "array":
        n = int(schema.get("minItems") or 0)
        return [stub_from_schema(schema.get("items", {})) for _ in range(n)]
    if t == "string":
        return schema.get("default", "")
    if t in ("number", "integer"):
        return schema.get("default", 0)
    if t == "boolean":
        return schema.get("default", False)
    if t == "null":
        return None
    return schema.get("default", None)


def stub_outputs(descriptor, ctx) -> Dict[str, Any]:
    """The `llm` fake: one schema-valid stub per declared output artifact (from the pinned output schemas)."""
    output_schemas: Dict[str, Any] = (ctx.extras or {}).get("output_schemas", {}) or {}
    produced: Dict[str, Any] = {}
    for out in descriptor.outputs:
        akey = out.model_dump(by_alias=True)["schema"].split("@", 1)[0]
        produced[akey] = stub_from_schema(output_schemas.get(akey, {}))
    # ADR-058 Phase C: an `llm` capability reasons before answering — surface a bounded rationale (the
    # sim model's reasoning stand-in) so explainability is exercised in dev/CI. Structural key; content
    # value. A plain MCP tool has no rationale and never gets one (this is the llm path only).
    from amendia_telemetry import bound_rationale
    rationale = bound_rationale(
        f"[simulated reasoning] produced {', '.join(produced) or 'no output'} for "
        f"{descriptor.capability_id}")
    return {"outputs": produced, "log": f"stub inference for {descriptor.capability_id}",
            "exec_meta": {"rationale": rationale} if rationale else None}


class SchemaStubDeepAgentRunner:
    """A `deep_agent` runner that emits a schema-valid stub (no model, no `SIM_CAPABILITIES`) — the CI/dev
    default once the in-code simulation is gone. Deep_agent caps declare exactly one output artifact."""

    async def run(self, *, capability_id, prompt_key, input_artifacts, tools, output_schema,
                  model_ref, budget, envelope, mcp_client: Optional[Any] = None,
                  title=None, description=None) -> Dict[str, Any]:
        return stub_from_schema(output_schema or {})
