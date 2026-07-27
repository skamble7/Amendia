# Amendia — Platform Domain-Neutrality Audit

**Status:** normative principle + remediation backlog.
**Principle (operator-stated, 2026-07-21):** *The platform must contain no code that assumes the seed data or
any particular test process. Amendia is a platform that onboards an arbitrary number of processes and
capabilities. Everything process-specific is **data** that flows through onboarding and lands in the registry;
the platform **code** must be domain-agnostic.*

The clean test: **onboarding a brand-new process, in a brand-new capability domain, backed by a brand-new MCP
server, must require zero change to platform code.** Where that is not true today, it is a leak.

## What is platform code vs. process data

- **Platform code** (must be domain-neutral): `process-registry` (onboarding state machine, inference,
  validators, DMN evaluator), `agent-runtime` (engine, compiler, executors), `libs/amendia_bpmn`,
  `libs/amendia_contracts`.
- **Process data** (lives in the registry, onboarded): BPMN, capability descriptors, artifact schemas, decision
  tables, MCP endpoints, capability **namespaces/domains**, roles, HITL modes, triage/policies.
- **Test fixtures** (exercise the platform, never assumed by it): `agent-runtime/seed/*`, `mcp_stub/*`,
  `stub_exception_generator/*`.

## Method

Static scan of platform code (excluding `seed/`, `tests/`, `mcp_stub/`, `stub_exception_generator/`, docstrings)
for domain terms (`wire|repair|dossier|sanction|beneficiary|payment|pacs|swift`). Each hit triaged as a
confirmed leak, a structural coupling, or a false positive.

## Confirmed leaks

| # | Leak | Location(s) | Why it's a leak | Sev | Generic remediation |
|---|------|-------------|-----------------|-----|---------------------|
| L1 | Capability **namespace defaults to `"payment"`** | `models/onboarding.py` (×2, `default_domain="payment"`), `services/onboarding.py:189` (`else "payment"`), `services/inference.py:103` (`or "payment"`) | A new pack silently inherits a business domain; this is what caused the `cap.payment.*` collision with the seed | High | No default business domain. Operator sets the domain (or it derives from `pack_key`); never fall back to a hardcoded area. Reject/flag a capability id that collides with an active catalog entry. |
| L2 | Runtime **auto-seeds a specific process on boot** | `process-registry/app/config.py:18`, `agent-runtime/app/config.py:17` (`_DEFAULT_SEED_DIR = …/seed/wire-repair-standard`) | The platform starts by loading one particular process | High | Seeding is opt-in / env-driven; prod boots with nothing seeded. No hardcoded default seed path. |
| L3 | **In-code capability implementations** | `agent-runtime/app/capabilities/wire_repair/*` (`enrich.py`, `assess.py`, `draft_rfi.py`, …), `screening.py`, `payment_comp.py`, `composition.py` | Wire-transfer business logic compiled into the platform runtime, referenced by seed `skill`-kind caps (`app.capabilities.wire_repair.enrich:run`) | High / structural | Runtime carries no per-process code. Capabilities resolve from registered descriptors; the built-in `skill` package moves to an external MCP server / example plugin / test fixture. → **ADR-047**. |
| L4 | **LLM/deep_agent executor framing hardcodes the domain** | `executor/dispatch.py:107` ("…in a **payments** exception-repair workflow"), `executor/deep_agent.py:39/52/137` (`search_payment_history`, "payments exception"), `validation/deep_agent.py:21` (`search_payment_history`) | Executor system prompts + tool lists bake in the domain | Med-High | Build executor framing from the capability **descriptor** (registered `prompt_key`/prompt, `runtime.tools`). No hardcoded domain string or tool name. Move the wire-specific deep_agent tools to the fixture. |
| L5 | Runtime **imports a wire-specific contract** + reaches into payment-shaped fields | `services/dispatch_service.py:22` (`from amendia_contracts.wire_exception import WireExceptionEnvelope`), `executor/mcp_client.py:73`, `capabilities/screening.py:18`, `capabilities/payment_comp.py` (`envelope["payment"]["creditor"]["name"]`, `["uetr"]`) | The engine hardcodes the trigger payload shape | High / structural | The start/trigger payload is a generic typed artifact whose schema is process data. The engine treats it opaquely (maps via bindings/`expr`); no hardcoded envelope import or field paths. → **ADR-047**. |

## Not violations (false positives)

- `engine/compiler.py:_wire_mi_out`, `parser.py` `wired` — "wire" here is graph-wiring (connecting nodes), not
  wire transfers.
- Docstrings in `model.py`, `parser.py`, `mcp_client.py`, `base.py`, `executor/expr.py` using "payment rejected /
  screening hit / `beneficiary.repair_verdict`" as **examples** of a modeled business error or an expression —
  benign, though the examples would ideally be generic too (a cheap follow-up, not a blocker).

## Remediation sequencing

- **P0 — unblocks clean onboarding (small, generic):** L1 (remove the domain default + add the collision
  guardrail) and L2 (seeding opt-in). After P0, onboarding a process in any domain, with no seed present, is the
  default path. *This is the prerequisite for the MCP-backed onboarding runbook.*
- **P1 — executor neutrality:** L4 (descriptor-driven LLM/deep_agent framing).
- **P2 — structural (ADR-047):** L5 (generic trigger artifact) and L3 (no per-process capability code in the
  runtime image). These are larger and re-home the seed's `skill` capabilities as an external MCP server /
  fixture — which the MCP-per-process direction already motivates.

## Acceptance

1. A scan of platform code for domain terms returns only generic examples in comments/docstrings — no domain
   literal in a default, a fallback, a prompt, an import, or a field path.
2. Booting the platform with no seed configured works; nothing wire-transfer-specific is loaded.
3. Onboarding a new process in a fresh domain (`cap.<newdomain>.*`) backed by a fresh MCP server validates and
   activates with **zero** platform code change.
4. The seed process (`wire-repair-standard`) and the MCP stub still work — but only as onboarded data / a fixture
   the platform loads, never as code the platform assumes.

## Companion artifacts

- **ADR-047** — the structural decisions (generic trigger artifact; runtime carries no per-process capability
  code).
- **`claude_code_prompt_domain_neutrality_batch.md`** — the sequenced Claude Code prompts (P0 → P2).
- **`amendia_mcp_backed_onboarding_runbook.md`** — the clean MCP-backed onboarding (executes after P0).
