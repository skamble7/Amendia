# app/services/mcp_introspect.py
"""MCP server introspection + tool→capability inference.

Two concerns live here:

1. **Introspection client** — an injectable :class:`McpIntrospector` that connects to a
   *running* MCP server (operator-supplied URL — an SSRF surface, hence owner-gated +
   timeout-bounded), performs the handshake, and calls ``tools/list``. The real
   implementation uses the official ``mcp`` client (lazily imported so tests can inject a
   fake without the dependency). We never echo response bodies beyond the tool schemas.

2. **Inference** — per the MCP Implementor Guideline, each *compliant* tool becomes an
   input artifact schema, an output artifact schema, and one ``kind: mcp`` capability. A
   tool missing ``outputSchema``, or whose schema root is a non-object, or that carries an
   external ``$ref``, is **non-compliant** and cannot be onboarded.
"""
from __future__ import annotations

import asyncio
import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.models.onboarding import (
    IdCollision,
    IntrospectedTool,
    StagedArtifact,
    StagedCapability,
    ToolCompliance,
)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_INTROSPECT_TIMEOUT_S = 12.0

# An amendia.dev registered-schema $id (the only external $ref we tolerate downstream).
_AMENDIA_ID_RE = re.compile(
    r"^https://amendia\.dev/schemas/artifacts/[a-z0-9_]+/[a-z0-9_]+/\d+\.\d+\.\d+\.json$"
)


class McpConnectionError(Exception):
    """Structured connection/handshake failure (→ HTTP 502 with a clean message)."""


def _open_streamable_http(url: str, headers: Optional[Dict[str, str]]):
    """Open a streamable-http MCP session as an async context manager, tolerant of the SDK's rename +
    signature change: `streamablehttp_client(url, headers=...)` → `streamable_http_client(url, *,
    http_client=...)` (headers now ride on an httpx client). Prefers the current API; falls back to the legacy
    one so introspection works across mcp versions."""
    from mcp.client import streamable_http as _shttp
    new = getattr(_shttp, "streamable_http_client", None)
    if new is not None:
        factory = getattr(_shttp, "create_mcp_http_client", None)
        if headers and factory is not None:
            return new(url, http_client=factory(headers=headers))
        return new(url)
    old = getattr(_shttp, "streamablehttp_client", None)
    if old is not None:
        return old(url, headers=headers)
    raise McpConnectionError(  # pragma: no cover - dependency guard
        "the installed mcp package exposes no streamable-http client "
        "(neither streamable_http_client nor streamablehttp_client)"
    )


@dataclass
class RawMcpTool:
    name: str
    description: Optional[str]
    input_schema: Optional[Dict[str, Any]]
    output_schema: Optional[Dict[str, Any]]


class McpIntrospector(Protocol):
    """The seam tests replace with an in-memory fake (no live network in CI)."""

    async def list_tools(
        self, *, endpoint: str, transport: str, headers: Dict[str, str]
    ) -> List[RawMcpTool]:
        ...


# --------------------------------------------------------------------------- #
# Real client — lazy ``mcp`` import so importing this module never requires it.
# --------------------------------------------------------------------------- #

class RealMcpIntrospector:
    """Connects to a real MCP server over streamable_http (default) or SSE."""

    async def list_tools(
        self, *, endpoint: str, transport: str, headers: Dict[str, str]
    ) -> List[RawMcpTool]:
        try:
            return await asyncio.wait_for(
                self._list_tools(endpoint=endpoint, transport=transport, headers=headers),
                timeout=_INTROSPECT_TIMEOUT_S,
            )
        except asyncio.TimeoutError as exc:
            raise McpConnectionError(
                f"MCP server did not respond within {_INTROSPECT_TIMEOUT_S:.0f}s"
            ) from exc

    async def _list_tools(
        self, *, endpoint: str, transport: str, headers: Dict[str, str]
    ) -> List[RawMcpTool]:
        try:
            from mcp import ClientSession  # lazy
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise McpConnectionError(
                "MCP client library is not installed on the registry service"
            ) from exc

        if transport == "sse":
            from mcp.client.sse import sse_client
            opener = sse_client(endpoint, headers=headers)
        else:
            opener = _open_streamable_http(endpoint, headers)

        try:
            async with opener as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
        except McpConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any transport/handshake error cleanly
            raise McpConnectionError(f"could not introspect MCP server: {exc}") from exc

        out: List[RawMcpTool] = []
        for t in listed.tools:
            out.append(
                RawMcpTool(
                    name=t.name,
                    description=getattr(t, "description", None),
                    input_schema=getattr(t, "inputSchema", None),
                    output_schema=getattr(t, "outputSchema", None),
                )
            )
        return out


# --------------------------------------------------------------------------- #
# Inference helpers
# --------------------------------------------------------------------------- #

def sanitize_name(raw: str) -> str:
    """Tool name → ``[a-z0-9_]`` artifact/capability name segment."""
    s = re.sub(r"[^a-z0-9_]+", "_", (raw or "").lower()).strip("_")
    return s or "tool"


def canonical_artifact_id(artifact_key: str, version: str) -> str:
    _, domain, name = artifact_key.split(".", 2)
    return f"https://amendia.dev/schemas/artifacts/{domain}/{name}/{version}.json"


def _collect_refs(node: Any, out: List[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                out.append(v)
            else:
                _collect_refs(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, out)


def _is_external_ref(ref: str) -> bool:
    """A ``$ref`` we refuse: an absolute URL that is not an amendia.dev registered id.
    Local pointers (``#/$defs/...``) are fine."""
    if ref.startswith("#"):
        return False
    if "://" in ref and not _AMENDIA_ID_RE.match(ref):
        return True
    # bare relative file refs are also external to the registry
    return "://" not in ref and not ref.startswith("#")


def _opaque_object_paths(schema: Any, path: str = "") -> List[str]:
    """ADR-057: property paths declared ``type: object`` with no (or empty) ``properties`` — an opaque object.
    Amendia derives a HITL review form from the declared shape; an opaque object has no field-level shape to
    derive, so it renders as a raw JSON editor and can't be validated field-by-field. Recurses through
    ``properties`` and array ``items``. The root itself is never flagged (an empty root just means no inputs)."""
    out: List[str] = []
    if not isinstance(schema, dict):
        return out
    props = schema.get("properties")
    if path and schema.get("type") == "object" and not (isinstance(props, dict) and props):
        out.append(path)
    if isinstance(props, dict):
        for name, sub in props.items():
            out.extend(_opaque_object_paths(sub, f"{path}.{name}" if path else str(name)))
    items = schema.get("items")
    if isinstance(items, dict):
        out.extend(_opaque_object_paths(items, f"{path}[]" if path else "[]"))
    return out


def evaluate_compliance(tool: RawMcpTool) -> ToolCompliance:
    """MCP Implementor Guideline verdict. ``reasons`` block (R1–R4); ``warnings`` advise but never block —
    Amendia can't force third-party servers to declare nested shapes, so an opaque object is a warning."""
    reasons: List[str] = []
    if tool.output_schema is None:
        reasons.append("missing outputSchema — a compliant tool must declare its output shape")
    for label, schema in (("inputSchema", tool.input_schema), ("outputSchema", tool.output_schema)):
        if schema is None:
            continue
        if not isinstance(schema, dict):
            reasons.append(f"{label} must be a JSON Schema object")
            continue
        if schema.get("type") not in (None, "object"):
            reasons.append(f"{label} root type must be 'object', got '{schema.get('type')}'")
        refs: List[str] = []
        _collect_refs(schema, refs)
        for ref in refs:
            if _is_external_ref(ref):
                reasons.append(f"{label} carries an external $ref '{ref}' (not allowed)")
    warnings: List[str] = []
    for prop_path in _opaque_object_paths(tool.input_schema):
        warnings.append(
            f"{tool.name}.{prop_path} is an untyped object — its HITL form will be a raw editor unless the "
            f"schema declares its properties"
        )
    return ToolCompliance(compliant=not reasons, reasons=reasons, warnings=warnings)


def normalize_artifact_schema(
    raw: Optional[Dict[str, Any]], *, artifact_key: str, version: str
) -> Tuple[Dict[str, Any], List[str]]:
    """Rewrite a tool schema into a registerable artifact json_schema.

    Forces root ``type: object``, draft-2020-12 ``$schema``, canonical ``$id``, and defaults
    ``additionalProperties: false`` (warning when the source was open). Raises on an external
    ``$ref`` (defence in depth; compliance already gated this)."""
    warnings: List[str] = []
    schema: Dict[str, Any] = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    schema["$schema"] = DRAFT_2020_12
    schema["type"] = "object"
    schema["$id"] = canonical_artifact_id(artifact_key, version)
    if "additionalProperties" not in schema:
        schema["additionalProperties"] = False
        warnings.append(f"{artifact_key}: source schema was open; defaulted additionalProperties=false")

    refs: List[str] = []
    _collect_refs(schema, refs)
    for ref in refs:
        if _is_external_ref(ref):
            raise ValueError(f"external $ref '{ref}' is not allowed in artifact schema '{artifact_key}'")
    return schema, warnings


def suggest_ids(tool_name: str, domain: str) -> Dict[str, str]:
    name = sanitize_name(tool_name)
    return {
        "input_artifact_key": f"art.{domain}.{name}_input",
        "output_artifact_key": f"art.{domain}.{name}_output",
        "capability_id": f"cap.{domain}.{name}",
    }


def _io_artifact_keys(ios: Any) -> List[str]:
    """The bare artifact keys (no @range) an existing capability declares for its IO — for a contract diff."""
    return sorted(str(getattr(io, "schema_", "")).split("@", 1)[0] for io in (ios or []))


def classify_id_collision(active: List[Any], *, domain: str, tool: str) -> Optional[IdCollision]:
    """Batch-4: classify a derived ``cap.<domain>.<tool>`` id against the ACTIVE catalog descriptors for that
    id. ``None`` → no collision (a fresh id). Otherwise **benign** when the active descriptor is
    contract-compatible with what introspection would stage (``kind: mcp`` + the same input/output artifact
    keys) — a reuse opportunity — else **hard** (kind and/or IO contract differ → a later ``binding_io_mismatch``).
    Domain-neutral: assumes nothing about which ids exist; compares only against the live catalog."""
    if not active:
        return None
    from packaging.version import Version
    desc = max(active, key=lambda d: Version(d.version))
    ids = suggest_ids(tool, domain)
    want_in, want_out = [ids["input_artifact_key"]], [ids["output_artifact_key"]]
    a_kind = desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)
    a_in, a_out = _io_artifact_keys(desc.inputs), _io_artifact_keys(desc.outputs)
    compatible = a_kind == "mcp" and a_in == want_in and a_out == want_out
    return IdCollision(
        capability_id=ids["capability_id"],
        severity="benign" if compatible else "hard",
        active_version=desc.version,
        active_kind=a_kind,
        diff=(f"active: kind={a_kind}, in={a_in or []}, out={a_out or []}; "
              f"introspected: kind=mcp, in={want_in}, out={want_out}"),
    )


# ADR-052 E3: MCP Implementor Guideline §4 — an ACTION (side-effectful) tool's output carries the
# acknowledgement shape. Amendia can't otherwise infer side-effectfulness from MCP, so this deterministic
# signal is the default (operator-overridable in the Capabilities step).
_ACK_FIELDS = frozenset({"acknowledged", "action_id", "status"})


def carries_ack_shape(output_schema: Optional[Dict[str, Any]]) -> bool:
    """True when the tool output declares the acknowledgement shape (acknowledged + action_id + status)."""
    if not isinstance(output_schema, dict):
        return False
    props = output_schema.get("properties")
    return isinstance(props, dict) and _ACK_FIELDS.issubset(props.keys())


def introspect_response_tool(tool: RawMcpTool, *, domain: str) -> IntrospectedTool:
    """Shape one tool for the introspection response, with suggested ids when compliant."""
    compliance = evaluate_compliance(tool)
    ids = suggest_ids(tool.name, domain) if compliance.compliant else {}
    return IntrospectedTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        compliance=compliance,
        suggested_input_artifact_key=ids.get("input_artifact_key"),
        suggested_output_artifact_key=ids.get("output_artifact_key"),
        suggested_capability_id=ids.get("capability_id"),
        suggested_side_effect="side_effectful" if carries_ack_shape(tool.output_schema) else "read_only",
    )


def infer_capability(
    *,
    tool: str,
    endpoint: str,
    transport: str,
    headers: Dict[str, str],
    domain: str,
    input_schema: Optional[Dict[str, Any]],
    output_schema: Optional[Dict[str, Any]],
    input_artifact_key: str,
    output_artifact_key: str,
    capability_id: str,
    artifact_version: str,
    capability_version: str,
    side_effect: str,
    idempotent: Optional[bool],
    min_hitl_mode: Optional[str],
    title: Optional[str],
    description: Optional[str],
) -> Tuple[StagedArtifact, StagedArtifact, StagedCapability, List[str]]:
    """Produce the two staged artifacts + the staged mcp capability for one selected tool.

    Raises ``ValueError`` if the tool is non-compliant (missing output schema, external
    ``$ref``, non-object root) — those cannot be onboarded."""
    verdict = evaluate_compliance(
        RawMcpTool(name=tool, description=description, input_schema=input_schema, output_schema=output_schema)
    )
    if not verdict.compliant:
        raise ValueError(f"tool '{tool}' is non-compliant: {'; '.join(verdict.reasons)}")

    in_name = sanitize_name(tool) + "_input"
    out_name = sanitize_name(tool) + "_output"

    in_schema, w1 = normalize_artifact_schema(
        input_schema, artifact_key=input_artifact_key, version=artifact_version
    )
    out_schema, w2 = normalize_artifact_schema(
        output_schema, artifact_key=output_artifact_key, version=artifact_version
    )
    warnings = w1 + w2

    input_artifact = StagedArtifact(
        artifact_key=input_artifact_key, version=artifact_version,
        title=f"{title or tool} input", json_schema=in_schema, source_tool=tool,
    )
    output_artifact = StagedArtifact(
        artifact_key=output_artifact_key, version=artifact_version,
        title=f"{title or tool} output", json_schema=out_schema, source_tool=tool,
    )
    capability = StagedCapability(
        capability_id=capability_id, version=capability_version,
        title=title or f"{tool} (MCP)", description=description,
        side_effect=side_effect, idempotent=idempotent, min_hitl_mode=min_hitl_mode,
        input_name=in_name, input_artifact_key=input_artifact_key,
        output_name=out_name, output_artifact_key=output_artifact_key,
        endpoint=endpoint, tool=tool, transport=transport, headers=headers,
        source_tool=tool,
    )
    return input_artifact, output_artifact, capability, warnings
