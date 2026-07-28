# ADR-052 — Business-facing onboarding (describe → review → approve), and the deterministic engine it stands on

**Status:** Proposed (2026-07-27)
**Related:** ADR-045 (persona inference), ADR-047/048/049/050/051 (the executable model + wizard the runtime already supports), `amendia_operating_model.md` (the four roles + gates), `amendia_design_signoff.md` (the design sign-off gate).

## Context

The people who will onboard a process are **business users — non-technical** (back-office SMEs, process
owners). The current onboarding wizard exposes the *executable graph directly*: bindings, input sources,
gateway variables, `schema_ref`s, artifact `$id`s, HITL modes, side-effect classification. Onboarding a
*deliberately simple* restaurant process through it took roughly a dozen manual technical steps and surfaced a
string of platform traps (wrong input-source guesses, un-derived gateway source-artifacts, empty SoD, a
`$id`-domain footgun, an inner-vs-whole schema paste ambiguity, a revise-loop uniqueness bug). Every one of
those is either derivable by the system or a platform defect — none is a decision a business user should make.

This is a **persona mismatch**, not a polish problem. The operating model already separates roles: back-office
SMEs own the *as-is*, AI/process experts design the *to-be*, MCP developers build capabilities, operators run
it. The business user's real jobs are **discovery**, **design sign-off**, and **go-live acceptance** — all in
*business* language. The current wizard forces the business user to *be the AI expert* and hand-wire the graph.

Separately (and this is the good news): the runtime, model, and validator are sound. The restaurant pack
reached **zero validation errors** — the platform executes the process correctly; what failed the user was the
*authoring surface*.

## Decision

**Onboarding becomes two surfaces for two personas.**

1. **Business-facing onboarding is the default: describe → review → approve, in plain language.** The business
   user supplies the process (the discovery as-is BPMN, a natural-language description, or a document) and
   points at the systems it touches. A **copilot** generates the entire technical configuration — bindings,
   input sources, HITL placement, triage, schemas, gateways — using the deterministic engine for the
   mechanical parts and an LLM only for the semantic leaps rules can't make. The business user reviews a
   **plain-language summary** ("when an order comes in, the kitchen checks it can be made; a manager approves
   firing it and taking payment; …") and adjusts *that* — who approves what, where a human must sign off —
   never JSON. **This review is the design-sign-off gate, rendered for a non-technical person.**
2. **The technical wizard becomes the expert / inspection view** for AI experts and MCP developers to verify or
   tweak an edge case. It is not the front door and is never shown to a business user.
3. **Safety stays deterministic.** The deterministic validator and the go-live acceptance gate remain the
   floor: everything the copilot proposes is validated structurally and for control-placement before a human
   accepts it. The copilot proposes; deterministic checks + an accountable human dispose. Amendia's own
   methodology, applied to its own onboarding.

This keeps the platform **domain-agnostic**: the copilot and the deterministic engine generate *into* the
neutral model (ADR-047); no domain logic enters the platform.

## The deterministic engine must be complete (this ADR's immediate scope)

The copilot and the business review are only as good as the engine underneath. Two defects and one auto-fill
gap remain, and they are this ADR's first, shippable phase:

- **E1 · Supersede uniqueness.** Allow the same human/message output *name* across tasks when they reference
  the *same* artifact (the revise-loop supersede — the runtime reads the latest write); still reject the same
  name on *different* artifacts. (Fixes the `order` collision.)
- **E2 · `$id` auto-normalize.** Derive an artifact's canonical `$id` from its key on registration and
  set/override it; never reject a mismatch. (Kills the `$id`-domain footgun.)
- **E3 · Deterministic auto-fill.** The wizard derives, the operator reviews: input sources (match by
  name+schema, re-run on human-output declaration, leave `trigger` when no match — never a wrong producer),
  gateway source-artifact (from the variable's first segment → the named output's artifact), SoD candidates
  (pre-populate the inferred four-eyes pairs), side-effect default (from the tool's ack-shape output), and
  schema paste (accept the inner schema *or* the whole artifact file).

## Consequences

- **+** Business users onboard in their own language; the technical detail is generated and validated for them.
- **+** Technical experts keep a precise view; nothing is hidden, just not *required* of the wrong person.
- **+** The model + validation work (ADR-047–051) is the foundation — it's what lets *any* process be
  represented and checked, and it is exactly what the copilot writes to.
- **−** This is a product-direction shift, not a bug fix: the primary onboarding surface changes. Phased below.

## Rollout (phased)

- **Phase 0 — model completeness (done):** ADR-049/050/051 — the config can be represented + validated.
- **Phase 1 — deterministic engine completeness (this ADR, now):** E1 supersede, E2 `$id`, E3 auto-fill. The
  technical wizard becomes a correct, low-touch expert view.
- **Phase 2 — the copilot:** generate the full config from a process description + the available capabilities
  (deterministic engine for the mechanics, LLM for the semantic leaps); output the neutral model.
- **Phase 3 — the business review UX:** plain-language describe → review → approve; the wizard demotes to the
  expert/inspection view.

## Non-goals

- Not removing the executable model or the technical view — experts still need it.
- Not blind automation — deterministic validation + an accountable human sign-off remain mandatory.
