# Claude Code Prompts — Platform domain-neutrality remediation (sequenced batch)

Excise the domain leaks catalogued in `amendia_platform_domain_neutrality_audit.md`. **The platform must not
assume the seed data or any test process.** Every change below is generic — no wire/payment/repair literal may
remain in a default, fallback, prompt, import, or field path. Land in order; P0 is the prerequisite for the
MCP-backed onboarding runbook. Recon each file first; do not hardcode the test process anywhere.

---

## P0 · Remove domain/seed defaults + add the collision guardrail (leaks L1, L2)

**L1 — no default capability domain.**
- `process-registry/app/models/onboarding.py`: remove `default_domain: str = "payment"` (both occurrences). Make
  the domain **operator-supplied** — required on the create-session request, or derived deterministically from
  `pack_key` if you choose a derivation rule (document it). No business-area default.
- `process-registry/app/services/onboarding.py:~189`: remove the `else "payment"` fallback. If the domain is
  absent/invalid, raise a clean `TransitionError(422, {...})` naming the field — never substitute a business
  area.
- `process-registry/app/services/inference.py:~103`: remove the `or "payment"` fallback; take the domain from the
  session/request and propagate it. If a domain is genuinely unavailable at inference time, that is a caller bug —
  surface it, don't paper over it with `payment`.
- **Collision guardrail (the actual fix for the reported bug):** at MCP introspection / capability staging, when a
  derived capability id (`cap.<domain>.<tool>`) **collides with an already-active capability** in the catalog,
  flag it as a non-committable finding at the **Capabilities step** (e.g. `capability_id_collision`, naming the id
  and the active version), and steer the operator to a distinct domain. This is generic — it compares against the
  live catalog, assuming nothing about which ids exist.

**L2 — seeding is opt-in, not a hardcoded process.**
- `process-registry/app/config.py` and `agent-runtime/app/config.py`: remove the hardcoded
  `_DEFAULT_SEED_DIR = …/seed/wire-repair-standard`. Seeding must be **env/flag-driven** (e.g. a `SEED_DIR` env
  var, unset by default) — with no seed configured, the service boots clean and seeds nothing. The
  `wire-repair-standard` path may appear only in a **local/dev compose or test config**, never as a code default.

**Tests:** creating a session without a domain returns a clear 422 (not a silent `payment`); a staged capability
whose id collides with an active one is flagged at the Capabilities step; the service boots with `SEED_DIR` unset
and loads nothing. No test asserts the string `payment` as a platform default.

**Docs:** onboarding guide — the domain is operator-chosen and must be process-scoped to avoid colliding with the
active catalog; note the collision guardrail. No ADR (config/validation on existing semantics).

---

## P1 · Descriptor-driven LLM/deep_agent executor framing (leak L4)

- `agent-runtime/app/engine/executor/dispatch.py:~107` and `executor/deep_agent.py:~137`: the system prompt must
  be built from the **capability descriptor** — its registered `prompt_key`/prompt text and its declared
  input/output artifacts — **not** a hardcoded "You are the '{id}' capability in a payments exception-repair
  workflow" string. The generic framing states the capability's role from the descriptor and the artifact it must
  produce; the domain comes entirely from registered data.
- `executor/deep_agent.py:~39/52` and `validation/deep_agent.py:~21`: remove the hardcoded `search_payment_history`
  tool (and any sibling domain tools) from the platform. A `deep_agent` capability's tools come from its
  descriptor's `runtime.tools`; the wire-specific investigative tools move to the test fixture / MCP server.
- Confirm no other executor path embeds a domain noun in a prompt or a tool list.

**Tests:** a `deep_agent`/`llm` capability with a registered prompt renders its framing from the descriptor; no
platform test depends on a hardcoded domain tool; the wire-transfer deep_agent behaviour is preserved via the
fixture, not engine code.

**Docs:** note in the capability-descriptor reference that `llm`/`deep_agent` framing and tools are fully
descriptor-sourced. No ADR (neutrality on existing semantics), or fold under ADR-047 if you prefer one record.

---

## P2 · Generalize the trigger envelope (leak L5 — ADR-047 D1)

- `agent-runtime/app/services/dispatch_service.py:~22`: remove `from amendia_contracts.wire_exception import
  WireExceptionEnvelope`. The engine receives the trigger as a **generic typed artifact** placed into process
  state under the pack's declared start-artifact key; it does not import a concrete envelope type.
- `executor/mcp_client.py:~73`, `capabilities/screening.py`, `capabilities/payment_comp.py`: remove hardcoded
  payload paths (`envelope["payment"]["creditor"]["name"]`, `["uetr"]`). All trigger/artifact field access goes
  through binding IO maps + the `expr` dotpath resolver against `artifacts[...]`.
- `WireExceptionEnvelope` remains in `libs/amendia_contracts` as a **registrable artifact schema** used only by
  the wire-transfer test pack (data), registered at onboarding as that pack's trigger artifact. The engine treats
  it as opaque.

**Tests:** the engine runs a pack whose trigger is a non-wire artifact with zero code change; the wire-transfer
pack still runs with its trigger registered as data. No engine module imports a wire/payment contract.

**ADR:** ADR-047 (D1).

---

## P2 · De-code capabilities from the runtime image (leak L3 — ADR-047 D2)

- Re-home `agent-runtime/app/capabilities/wire_repair/*`, `screening.py`, `payment_comp.py`, `composition.py` out
  of the platform package. Preferred: express them as **`mcp` tools** on the wire-transfer MCP server (already
  exists in `mcp_stub`) and re-onboard the seed packs against it. If an in-process `skill` is genuinely required,
  load it via an **external plugin/entry-point** resolved at deploy time — not a package imported by engine code.
- Remove engine imports of `SIM_CAPABILITIES` (`executor/core.py`, `deep_agent.py`, `openshell/client.py`) and
  the `app.capabilities.wire_repair` dependency. `skill`-kind resolution, if retained, goes through the external
  mechanism.
- Move any tests importing `SIM_CAPABILITIES`/`WireExceptionEnvelope` from the engine to the fixture layer.

**Tests:** `grep` of `agent-runtime/app` for `wire_repair|payment|dossier|sanction` returns nothing outside
generic docstrings; the platform image builds and boots with no per-process capability module; the wire-transfer
seed still executes, now via MCP/plugin, not engine Python.

**ADR:** ADR-047 (D2). This is the larger track; the MCP-backed onboarding runbook is its end-to-end proof.

---

## Global definition of done

A scan of platform code (`process-registry/app`, `agent-runtime/app`, `libs/amendia_bpmn`,
`libs/amendia_contracts`) for `wire|repair|dossier|sanction|beneficiary|payment|pacs` returns only generic
examples in comments/docstrings — no domain literal in any default, fallback, prompt, import, or field path.
Booting with no seed works. Onboarding a fresh-domain, fresh-MCP process validates, activates, and executes with
zero platform-code change. The wire-transfer seed still works — as onboarded data / a fixture, never as code the
platform assumes.
