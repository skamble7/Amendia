# Claude Code Prompt — Capability-id collision guardrail at the Capabilities step (batch-4)

The whole `ws-stan` collision saga started because MCP introspection derived `cap.payment.<tool>` ids that already
existed as **active** capabilities from the seed (a different `skill`/`llm` contract). The pack's refs then
resolved to those pre-existing capabilities, and every binding failed `binding_io_mismatch` — but only at the
final assemble dry-run, deep into onboarding. Catch it at the **Capabilities step**, when the operator introspects
or stages, and steer them to a distinct domain or explicit reuse. Domain-neutral (ADR-047): compare derived ids
against the live catalog; assume nothing about which ids exist.

## Recon

- `backend/services/process-registry/app/services/mcp_introspect.py` + `onboarding.py::set_capabilities` — where
  introspected tools become staged capabilities with derived `cap.<domain>.<tool>` ids.
- `app/routers/capabilities.py` + `dal/capability_repo.py` — the active catalog (`list`, `get`) to check ids
  against.
- `app/services/onboarding.py::_capability_descriptor` — the staged descriptor (kind + IO) to compare contracts.
- `webui/src/features/registry/OnboardingWizard.tsx::CapabilitiesStep` — where to surface the flag + actions.

## Change 1 · Backend — detect the collision on introspect/stage

When deriving/staging a capability id `cap.<domain>.<tool>`:

- Look it up in the **active** catalog. If an active capability with that id exists, classify:
  - **Hard collision** — the active capability's descriptor (kind and/or input/output artifact contract) **differs**
    from what introspection would stage. Emit a **non-blocking finding** `capability_id_collision` carrying the id,
    the active version, and a short contract diff ("active: kind=skill, in=[repair,screening]; introspected:
    kind=mcp, in=[<tool>_input]"). This is the exact condition that later becomes `binding_io_mismatch`.
  - **Benign match** — the active descriptor is contract-compatible: this isn't a collision, it's a **reuse
    opportunity**; suggest reusing the existing capability instead of staging a duplicate.
- Return these findings from the introspect endpoint and/or `set_capabilities` response so the wizard can render
  them per-tool. Do **not** block — the operator decides.

## Change 2 · Wizard — surface it with two clear fixes

At the Capabilities step, for each tool flagged `capability_id_collision`, show an inline warning with two
one-click actions:

- **Use a distinct domain** — the id collides because the pack's domain (`payment`) is already occupied. Offer to
  change the pack's `default_domain` to a process-scoped one (e.g. derived from `pack_key`) so every derived id
  becomes `cap.<newdomain>.<tool>` — no collision. (Pairs with the P0 change that removes the hardcoded
  `default_domain="payment"`.)
- **Reuse the existing capability** — if the operator intends to use the already-registered one, add it to
  `reused_capability_refs` instead of staging a new (colliding) definition.

For a **benign match**, surface a lighter "already in the catalog — reuse?" nudge (not an alarm).

## Non-goals

- No auto-renaming and no blocking — the operator chooses domain-vs-reuse. No change to introspection semantics,
  the descriptor contract, or validation beyond the new advisory finding. No domain-specific id lists.

## Definition of done

- Introspecting a server whose tools derive ids that collide with active catalog capabilities of a **different**
  contract flags each colliding tool at the Capabilities step with the contract diff and the two fixes; choosing a
  distinct domain clears them. This would have caught the `ws-stan` `cap.payment.*` collision at introspect time
  instead of at assemble.
- A **contract-compatible** active id is surfaced as a reuse nudge, not a collision (no false alarm).
- A fresh domain with no catalog overlap produces zero findings. Backend test: collision vs benign-match
  classification; wizard test: the per-tool warning + actions render. `registry` + `webui` green.

## Batch-4 sibling

Ships alongside the capability pre-select recall (done) and the triage field/op validation. Together they move the
three authoring-time failures this run surfaced (unbound tasks, silent id collision, silent mis-triage) to the
step where the operator can fix them.
