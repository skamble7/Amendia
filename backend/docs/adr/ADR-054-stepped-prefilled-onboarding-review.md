# ADR-054 — Stepped, pre-filled onboarding review (the copilot fills the wizard)

**Status:** Proposed (2026-07-31)
**Related:** ADR-052 (business-facing onboarding), ADR-048/050/051 (dataflow, human-authored artifacts, nameable outputs), the Phase-2c copilot UX.

## Context

ADR-052 collapsed onboarding to *describe → review → approve*: the copilot generates the pack, the operator reads a
plain-language summary and refines by chat, then activates; the technical wizard was demoted to a hidden "inspection
view" behind a link.

Two real processes (restaurant, wire-transfer) were onboarded and executed end-to-end through it, and surfaced two UX
problems:

1. **The collapse hid the generated structure.** The copilot's value is eliminating manual *authoring* — nobody
   should hand-type bindings, input maps, or gateway variables. But "don't make them enter it" got conflated with
   "don't show it." An expert process owner needs to *see* the generated bindings, HITL placement, dataflow, and
   schemas to trust them. A paragraph plus a "View technical detail" link reduces confidence, not burden.

2. **Human-authored artifact forms render as JSON.** A HITL form is only as clean as the artifact schema behind it; a
   loosely-derived `object` becomes a raw JSON editor (e.g. the wire `proposed_value` field), which a business user
   can't fill.

The principle we'd lost: **prevent manual entry, not manual review.**

## Decision

1. **Onboarding becomes a stepped, pre-filled review, and it is the default.** The copilot still generates
   everything (no blank authoring), but the operator walks pre-filled, editable steps — **Understanding,
   Capabilities, Artifacts & schemas, Bindings (HITL + dataflow), Gateways, Trigger & triage, Review & go live** —
   each seeded from the generated session and adjustable. The plain-language summary and the chat-refine loop ride
   along. The terse two-step is retired. In effect, the copilot *fills the wizard*, and the wizard is promoted from a
   hidden inspection view back to the review surface.

2. **Human-authored artifact schemas: copilot drafts, operator refines.** In the Artifacts & schemas step, the
   operator edits the derived schema for each human-authored artifact — field types, labels, enums, required — so the
   HITL form renders as clean labeled fields (string inputs, enum dropdowns), with a **live form preview**. No blank
   authoring; the copilot's draft is the starting point.

3. **Safety unchanged.** Deterministic validation still gates activation; the copilot still proposes and reconcile
   still disposes. This is a *visibility and control* change to the review surface, not to generation or enforcement.

## Consequences

- **+** Expert process owners can verify and trust the generated config — confidence, not just brevity.
- **+** Business users filling HITL forms get clean labeled fields, because the schemas were refined at onboarding.
- **+** Reuses the existing wizard machinery (now pre-filled) — far less new UI than it sounds.
- **−** More clicks than the two-step — but *review* clicks, not entry; pre-fill keeps effort low.
- **−** The "pure business plain-language only" surface is deferred; the stepped review serves the process-owner
  persona who actually onboards today. (A lighter business-only mode can layer on later.)

## Non-goals

- Not reintroducing manual authoring — every step is pre-filled by the copilot.
- Not changing generation, reconcile, validation, or the runtime.
