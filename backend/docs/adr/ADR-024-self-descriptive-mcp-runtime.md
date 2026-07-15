# ADR-024 — Self-descriptive `mcp` capability runtime (drop the `server_key` indirection)

- **Status:** Accepted
- **Date:** 2026-07-15
- **Related:** ADR-016 (secret-refs / `literal:→vault:`), ADR-018 (ConfigForge = LLM ModelProfiles),
  ADR-019 (contract-derived egress policy), ADR-020 (in-sandbox MCP client), ADR-023 (OpenShell egress:
  `mcp` is a first-class protocol; an endpoint is an egress-policy entry).
- **Supersedes:** the `server_key` field of `McpRuntime` and the documented "`server_key` indirects into
  config-forge for the MCP server endpoint/auth" model (contracts reference / platform contracts v1).

## Context

A capability of `kind: "mcp"` declared a `server_key: str` on its `runtime` block — nominally a key that
indirects into ConfigForge to resolve the MCP server's endpoint + auth. Exploration established that this
indirection was **dead**:

- **ConfigForge never stored MCP servers.** Its `ConfigKind` enum allows only `llm`; it holds only polyllm
  ModelProfiles (ADR-018). No MCP entry ever existed, and the agent-runtime never queried config-forge for
  an MCP `server_key`.
- **The concrete endpoint lived elsewhere.** At runtime, `RegistryMcpClient` resolved `server_key` against a
  local JSON **file** (`AGENTRT_MCP_REGISTRY_PATH`, shaped `{server_key: {"url","transport"?,"headers"?}}`)
  and POSTed `tools/call` to `entry["url"]`. So the server's real details were split across the descriptor
  (`server_key`) and an out-of-band file — the opposite of self-describing.

The maintainer's preference: the capability descriptor should be a **self-descriptive model** — everything
needed to understand/execute an MCP capability visible in one place — rather than a key chased into another
service or file.

## Decision

Embed the MCP server connection details **directly on the capability's `runtime`**. Replace `server_key`
with:

```jsonc
"runtime": {
  "kind": "mcp",
  "endpoint": "http://stub-mcp:8056/mcp",   // the MCP server URL (self-descriptive)
  "tools": ["screen_party"],                 // whitelist — the agent gets these and nothing else
  "transport": "streamable_http",            // streamable_http (default) | stdio | sse
  "headers": {}                              // non-secret headers or secret-refs (env:/file:/vault:)
}
```

- **`endpoint`** hard-replaces `server_key` (no deprecated alias — nothing resolved it; only two identical
  seed descriptors + a couple of tests referenced it).
- **`headers`** carries non-secret headers or **secret-refs** (`env:`/`file:`/`vault:`) — **never a literal
  secret** (honours ADR-016 trap 1; matches the old registry-entry `{url, headers}` shape 1:1).
- **The MCP client is now direct.** `RegistryMcpClient` → `HttpMcpClient`: it drops the registry-file
  lookup and POSTs `tools/call` straight to the descriptor's `endpoint` with its `headers`. `StubMcpClient`
  (dev/CI, marker-based) is unchanged in behaviour. `AGENTRT_MCP_REGISTRY_PATH` is removed (config, compose,
  Helm) — nothing resolves it anymore.
- **Egress policy improves.** `derive_egress_policy` now parses the host straight from `runtime.endpoint`
  and adds it to `allow_hosts` — strictly better than the old "the gateway/config-forge resolves it" note.

## Consequences

- **Self-descriptive.** An MCP capability descriptor fully declares its server; no config-forge/registry
  indirection to chase. The egress allowlist is a pure function of the descriptor (endpoint host + tools).
- **Trade-off accepted:** the endpoint is now **environment-specific** — the same pack onboarded in dev vs
  prod needs the right `endpoint` (the very split-out that indirection avoided). Accepted "for now" per the
  self-descriptive preference; a future option is an env-interpolated endpoint placeholder if per-env forks
  become painful.
- **Secrets stay refs** (ADR-016 trap 1): `headers` values are non-secret or `env:`/`file:`/`vault:` refs;
  OpenShell may still broker credentials gateway-side.
- **Re-onboarding required.** Descriptors are versioned and immutable-once-onboarded, so the two seed packs
  (`wire-repair-standard`, `wire-repair-agentic`) must be re-onboarded (reset the `amendia` registry DB /
  re-seed) for the new runtime shape to take effect. No validator change is needed — `McpRuntime` is
  validated by pydantic; the registry never inspected `server_key`, and the `deep_agent` tool whitelist
  keys off `runtime.tools`, unaffected.

## Traps recorded for maintainers

1. **No secret in a header value.** `headers` holds non-secret headers or `env:`/`file:`/`vault:` refs —
   never a raw token. The descriptor is committed to Git and served by the registry.
2. **`endpoint` is env-specific.** Because it's embedded (not indirected), a descriptor pins one
   deployment's server. Bump the descriptor/pack version to change it; don't hand-edit an onboarded one.
3. **The client is direct now.** `HttpMcpClient` POSTs to `runtime.endpoint`; there is no registry file.
   Don't reintroduce `AGENTRT_MCP_REGISTRY_PATH` — the OpenShell in-sandbox MCP registry (if used) is a
   deploy-side credential-brokering detail, not the resolution path.
