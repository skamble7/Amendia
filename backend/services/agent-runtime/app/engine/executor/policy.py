# app/engine/executor/policy.py
"""Derive a per-capability egress/tool policy from *already-declared contract data*
(ADR-019 Part C) — not a parallel hand-maintained list.

The policy is a function of the capability descriptor:
  * ``mcp``   → the host parsed from the self-descriptive ``runtime.endpoint`` (ADR-024) +
                ``runtime.tools`` whitelist + ``transport``.
  * ``llm``   → the managed inference proxy host (``inference.local`` — **confirmed** against
                NemoClaw docs; the in-sandbox OpenAI-compatible endpoint is ``inference.local/v1``).
  * ``skill`` (side-effectful) → the specific rail/notification endpoint declared in the
                capability's ``config``/``config_schema`` (dev = stub endpoints).

**Enforcement note (confirmed):** OpenShell enforces egress via *sandbox-creation-time*
policy (CLI ``openshell policy set`` / provider + MCP registration during ``nemoclaw onboard``),
**not** a per-request field on an execute call — because OpenShell exposes no host→gateway
execute RPC (see ADR-019 §Findings). So this derived allowlist is what would feed sandbox
provisioning; it is carried on ``CapabilityRunSpec`` for that purpose and for auditability.
The deterministic fake ignores it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Confirmed against NemoClaw docs: the in-sandbox managed inference proxy is OpenAI-compatible
# at https://inference.local/v1 (host `inference.local`).
INFERENCE_PROXY_HOST = "inference.local"


@dataclass
class EgressPolicy:
    """A capability's derived egress + tool allowlist. All fields come from the contract."""

    kind: str
    side_effect: str
    allow_hosts: List[str] = field(default_factory=list)
    # mcp only
    mcp_endpoint: Optional[str] = None
    mcp_tools: List[str] = field(default_factory=list)
    mcp_transport: Optional[str] = None
    # llm / deep_agent
    inference_proxy_host: Optional[str] = None
    # deep_agent: the whitelisted toolset the harness may call
    agent_tools: List[str] = field(default_factory=list)
    # side-effect skill: endpoint keys declared in the capability config (dev = stub)
    skill_endpoints: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "side_effect": self.side_effect,
            "allow_hosts": sorted(set(self.allow_hosts)),
            "mcp": (
                {"endpoint": self.mcp_endpoint, "tools": self.mcp_tools,
                 "transport": self.mcp_transport}
                if self.mcp_endpoint else None
            ),
            "inference_proxy_host": self.inference_proxy_host,
            "agent_tools": self.agent_tools,
            "skill_endpoints": self.skill_endpoints,
            "notes": self.notes,
        }


def _kind(descriptor) -> str:
    k = descriptor.kind
    return k.value if hasattr(k, "value") else str(k)


def _side_effect(descriptor) -> str:
    se = getattr(descriptor, "side_effect", None)
    return se.value if hasattr(se, "value") else str(se)


def _endpoint_keys_from_config_schema(descriptor) -> List[str]:
    """Best-effort: property names in ``config_schema`` that look like an endpoint/URL.

    In dev these resolve to stub endpoints (no real rail/notification). We surface the
    declared keys so sandbox provisioning can allowlist exactly those and nothing else.
    """
    schema = getattr(descriptor, "config_schema", None) or {}
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    keys = []
    for name in props:
        low = name.lower()
        if any(tok in low for tok in ("endpoint", "url", "host", "rail", "webhook")):
            keys.append(name)
    return sorted(keys)


def derive_egress_policy(descriptor, *, llm_proxy_host: Optional[str] = None) -> EgressPolicy:
    """Build the egress/tool policy for a capability from its descriptor."""
    kind = _kind(descriptor)
    policy = EgressPolicy(kind=kind, side_effect=_side_effect(descriptor))

    if kind == "mcp":
        rt = descriptor.runtime
        policy.mcp_endpoint = getattr(rt, "endpoint", None)
        policy.mcp_tools = list(getattr(rt, "tools", []) or [])
        tr = getattr(rt, "transport", None)
        policy.mcp_transport = tr.value if hasattr(tr, "value") else (str(tr) if tr else None)
        # Self-descriptive (ADR-024): the egress host is parsed straight from the endpoint —
        # no gateway/config-forge resolution needed. Allowlist = endpoint host + tools whitelist.
        if policy.mcp_endpoint:
            from urllib.parse import urlparse

            host = urlparse(policy.mcp_endpoint).hostname
            if host:
                policy.allow_hosts.append(host)
        policy.notes.append(
            f"mcp egress restricted to endpoint host={sorted(set(policy.allow_hosts))}; "
            f"tools whitelist={policy.mcp_tools}"
        )

    elif kind == "llm":
        host = llm_proxy_host or INFERENCE_PROXY_HOST
        policy.inference_proxy_host = host
        policy.allow_hosts.append(host)
        policy.notes.append(f"llm egress restricted to managed inference proxy host={host}")

    elif kind == "deep_agent":
        host = llm_proxy_host or INFERENCE_PROXY_HOST
        policy.inference_proxy_host = host
        policy.allow_hosts.append(host)
        policy.agent_tools = list(getattr(descriptor.runtime, "tools", []) or [])
        # Injection resistance (design §9.6): a deep_agent reads UNTRUSTED attachments/
        # correspondence. The egress allowlist (inference proxy only) + the tool whitelist are
        # the mitigation — a hijacked loop can reach only what the contract granted.
        policy.notes.append(
            f"deep_agent egress restricted to inference proxy host={host}; tool whitelist="
            f"{policy.agent_tools} — the ONLY tools a (possibly injected) loop may call"
        )

    elif kind == "skill":
        if policy.side_effect == "side_effectful":
            policy.skill_endpoints = _endpoint_keys_from_config_schema(descriptor)
            policy.notes.append(
                "side-effectful skill: egress restricted to declared endpoint(s) "
                f"{policy.skill_endpoints or '[none declared → stub only in dev]'}; "
                "actual action stays simulated in dev (no real payment/notification)"
            )
        else:
            policy.notes.append("read-only skill: no/minimal egress (defense-in-depth)")

    return policy
