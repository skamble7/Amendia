# ADR-045 — Deepen swimlane / persona inference UX

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-027 (the inference draft — advisory pre-fills
from the diagram), ADR-044 (the full-bindable-set authoring surface + inventory), ADR-026 (`pack_roles`
sidecar). **Track:** Onboarding Track 3 — turn the rich inference the wizard already computes into pre-filled,
**explained, one-click defaults**, so onboarding a complete reference BPMN (lanes / pools / personas) feels like
*confirming inferences* rather than filling blank forms.

## Context — enrichment, not new plumbing

The inference→frontend surfacing spine already existed (ADR-027/044): `inference.py` emits lane roles,
per-binding `suggested_hitl_mode`, SoD candidates with a `rationale`, capability candidates, gateway variables,
external pools (`is_external`) + message flows; the wizard already pre-fills gateway variables, SoD pairs, roles,
role-meta **labels**, and binding executor/role/HITL with "from lane" chips. Track 3 fills the **specific gaps**
below — no new steps (the 7-step state machine is unchanged), no contract/validator/runtime change.

## Decision

### 1 · Lane persona → HITL default (the meaningful one)

`suggested_hitl_mode` was a pure verb heuristic that ignored the lane persona. It now matches the task's **lane
name** first (`_lane_intent`), then falls back to the verb heuristic:

- **agent / automation** lane ("AI Agent", "System", "Bot", "Runtime") → capability tasks start `none`;
- **analyst / maker / reviewer** lane ("Analyst", "Ops", "Maker", "Reviewer") → `review_after`;
- **approver / checker** lane ("Approver", "Checker", "Authorizer") → `approve_actions`;
- **supervisor / escalation** lane ("Supervisor", "Manager", "Escalation") → a `manual` gate.

(First keyword wins, ordered approver→supervisor→analyst→agent so "Ops Approver" reads as an approver, not an
analyst.) Applied to **capability** tasks; human tasks keep `manual`, message/call keep `none`.

**Hard invariant (unbroken):** this is only a *starting* suggestion. The assemble-time **side-effect→HITL
floor still governs** — a `side_effectful` capability is always ≥ `approve_actions` regardless of lane (the
inference doesn't know `side_effect`; the guard does). Documented: the lane sets a starting mode, the guard sets
the floor.

### 2 · Persona → role description

`InferredRole` gains a `description` derived from the lane's persona (an approver lane → "Four-eyes approver —
authorizes side-effectful actions before they execute.", an analyst lane → "Maker / analyst — reviews and
edit-approves agent output.", …; unrecognized → none). The Policies step seeds it into the `role_meta`
description field (previously blank), so personas carry their meaning through to the `pack_roles` sidecar
(ADR-026) and the Administration role picker. Operator-editable.

### 3 · Candidates become explained + confirmable (frontend)

- **SoD:** each pre-filled pair shows its `SodCandidate.rationale` as a dismissible "suggested" provenance chip
  ("'Draft repair' and 'Approve repair' are in different lanes — four-eyes candidate") — the operator sees *why*
  and accepts (keep) or removes.
- **Decision candidate:** a `businessRuleTask` flagged `decision_capability_candidate` shows a visible "decision
  table candidate" badge (with its provenance) in the Bindings step — Track 2 turns this into "author a table";
  here it is surfaced.
- **Provenance everywhere:** the "from lane" chip pattern is extended to roles (persona description), SoD
  (rationale), and external hints (message-flow name).

### 4 · Pool / external-system → capability scaffolding (frontend)

The Capabilities step splits inferred capability candidates into **task slots** (the existing "expects
capabilities" card) and **external integrations** — one actionable slot per external message flow, showing the
flow/pool name + the suggested capability id, with an "Introspect for this" action that focuses the MCP-server
field. The name is already carried by the inventory's `message_flows` + the `external_integration_hint`
annotation, so no backend change was needed for it.

## Consequences

- Onboarding the reference BPMN pre-fills HITL from lane persona (agent→none … approver→approve_actions),
  carries persona descriptions into `role_meta`, shows SoD/decision candidates with their rationale as
  confirmable suggestions, and turns external message flows into actionable capability-slot nudges — every
  inferred value showing its provenance, all operator-editable, the side-effect→HITL floor still hard. The flow
  feels like confirming inferences. Only `InferredRole.description` is a new model field → the registry OpenAPI
  snapshot + `registry.ts` were regenerated (additive). No contract/validator/runtime change; the verb-heuristic
  fallback preserves current behavior for lane-less BPMNs, so the standard / projection packs onboard
  byte-unchanged.

## Non-goals

- **Decision / reduce authoring** (Track 2) — the decision candidate is only *surfaced* here.
- The lane→HITL mapping is a **starting point, not a hard rule** — the side-effect floor is the only hard
  constraint. No new steps, no new execution/validation semantics.
