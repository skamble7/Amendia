# ADR-047 — Platform domain-neutrality: generic trigger artifact & runtime capability decoupling

**Status:** Proposed
**Date:** 2026-07-21
**Context owner:** Sandeep Kamble
**Supersedes/relates:** ADR-024 (self-descriptive capability descriptors), ADR-027 (ingest→execute conformance),
ADR-035 (real capability/business-error mapping), the MCP Implementor Guideline.

## Context

Amendia is a **platform**: it onboards an arbitrary number of processes and capabilities, and its code must
assume none of them. The Platform Domain-Neutrality Audit found two *structural* couplings (beyond the
config-level defaults handled in P0/P1) where the wire-transfer test process leaks into the platform runtime:

1. **The trigger payload shape is hardcoded.** `agent-runtime` imports `WireExceptionEnvelope` and several
   executors read fixed paths (`envelope["payment"]["creditor"]["name"]`, `["uetr"]`). A process whose trigger
   is not a wire exception cannot run without code change.
2. **Per-process capability logic lives in the platform image.** `agent-runtime/app/capabilities/wire_repair/*`
   (+ `screening.py`, `payment_comp.py`) are wire-transfer implementations referenced by the seed's `skill`-kind
   capabilities. The runtime ships a specific process's business logic.

Both violate the principle that *process specifics are data, not code*. This ADR fixes the structural half; the
config-level defaults (domain fallback, boot seed) are handled as P0 in the remediation batch.

## Decision

### D1 — The start/trigger payload is a generic, process-declared artifact

- A process pack **declares its trigger artifact schema** (registered like any other artifact). The engine
  receives the trigger as an opaque typed artifact instance placed into process state under a well-known key
  (e.g. `trigger` / the process's declared start artifact), and never imports a concrete envelope type.
- All field access into the trigger goes through the **binding IO maps** and the **`expr` resolver** (which
  already resolves dotpaths against `artifacts[...]`), exactly as capability-to-capability data does. No executor
  hardcodes a payload path.
- `WireExceptionEnvelope` moves to `libs/amendia_contracts` **as a registrable artifact schema used only by the
  wire-transfer test pack** — the engine no longer imports it. The `stub_exception_generator` emits an instance
  of that (data), which onboarding registers as the pack's trigger artifact.

### D2 — The runtime carries no per-process capability code

- Capability execution is **fully descriptor-driven**. For `mcp` the runtime already calls the descriptor's
  `endpoint`/`tools`; for `llm`/`deep_agent` the framing (system prompt, tool list) is built from the descriptor
  (`prompt_key`/registered prompt, `runtime.tools`) with **no hardcoded domain string or tool name** (this is L4,
  landed in P1).
- **`skill`-kind capabilities that require in-process Python are not part of the platform image.** Options, in
  preference order: (a) express the capability as `mcp`/`llm`/`deep_agent` (the onboardable kinds) — the
  preferred path, and the one the MCP-per-process model already takes; (b) if an in-process skill is genuinely
  needed, load it via an **external plugin/entry-point mechanism** resolved at deploy time, not from a package
  baked into `agent-runtime`.
- The existing `app/capabilities/wire_repair/*`, `screening.py`, `payment_comp.py` are **re-homed** as: the
  `mcp_stub` wire-transfer server (already exists) and/or an example plugin under a `fixtures/` tree — never
  imported by engine code. The seed `skill` caps that referenced them are re-onboarded against the MCP server (or
  marked example-only).

## Consequences

- **Positive:** the engine becomes a pure executor of onboarded manifests + registered artifacts + capability
  descriptors. A new process in a new domain with a new MCP server runs with zero platform change — the audit's
  acceptance test passes. The seed becomes one onboarded pack among many, not a privileged code path.
- **Cost:** the seed's `skill`/`deep_agent` capabilities must be re-homed (as MCP tools or an external plugin),
  and their packs re-onboarded to point at the new home. Tests that imported `SIM_CAPABILITIES` /
  `WireExceptionEnvelope` from the engine move to the fixture layer.
- **Migration:** staged — D1 (envelope) and the L4 executor framing first (mechanical), then D2's capability
  re-homing (larger). The MCP-backed onboarding of the wire-transfer process (the runbook) is the reference
  proof that D2's target state works end to end.

## Alternatives considered

- *Keep the `skill` code but gate it behind config.* Rejected — the platform image still ships a specific
  process's logic; the leak is presence, not activation.
- *Keep `WireExceptionEnvelope` as the universal trigger type.* Rejected — it names a business domain; a generic
  `trigger` artifact whose schema is process data is the neutral form.

## Acceptance

Same as the audit's: platform code scan clean of domain literals; boot-with-no-seed works; a fresh-domain,
fresh-MCP process validates/activates/executes with no code change; the wire-transfer pack still runs, now as
onboarded data pointing at the MCP server rather than in-engine Python.
