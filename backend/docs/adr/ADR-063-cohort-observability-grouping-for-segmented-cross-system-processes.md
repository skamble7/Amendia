# ADR-063 — Cohorts: observability grouping for segmented cross-system processes

**Status:** Proposed — 2026-08-08
**Date:** 2026-08-08
**Context owner:** Sandeep Kamble
**Relates:** ADR-047/049 (domain-neutral trigger schema; optional `declare_trigger`), ADR-031 (message
substrate / correlation), ADR-058 (GLEA observability on OTel + ClickHouse; `PackLifecycleEvent` /
`audit_events` SoR), ADR-019 (per-instance memoization), the dispatch/spawn path
(`agent-runtime` `DispatchService`), and the ingress path (`ingestor` → registry `/resolve` →
`trigger_dispatched`).

## Context

Amendia today assumes an onboarded process executes **in its entirety** inside Amendia: a trigger message
triages to a pack, agent-runtime spawns one instance, it runs to a terminal outcome. That holds for most
deployments.

In some enterprise deals it does not. A larger business process is **segmented** across systems — an external
orchestrator (e.g. Pega) owns the overall flow, executes some segments itself, and delegates other segments to
Amendia. Amendia is deliberately blind to the external segments; it only executes the segments assigned to it.
Each Amendia segment is onboarded and triggered **exactly like any ordinary process** — nothing about triage,
compilation, HITL gating, or execution changes.

What is missing is a way to recognise that several independently-triggered segment instances are **siblings of
one real-world case**, so they can be surfaced, monitored, audited, and reported **together** rather than as
unrelated instances. Concretely, in wire-transfer exception handling: exception `1v23p` may drive two Amendia
segments (triaging to two different packs) plus several Pega-owned steps; an operator looking at GLEA should be
able to see "everything Amendia did for `1v23p`" as one unit.

There is a real correlation handle available: the external world already stamps each trigger message with a
business key (here `exception_id`) that is common across all segments of the same case. Amendia can use that
key to tie its segments together **without any new coupling to the external system** — the external system
never needs to know Amendia's internal identifiers.

## Decision

Introduce a **Cohort**: a first-class, **purely observational** grouping of the Amendia segment instances that
belong to one real-world case, correlated by a business key drawn from the trigger message. For **V1 the cohort
has zero execution authority** — it does not sequence segments, pass data between them, gate, or terminate
anything. It observes; GLEA consolidates. It is explicitly **not a saga** (no coordination, no compensation).

### Definition vs instance (fixed vocabulary)

The cohort mirrors the pack/instance duality exactly, and we fix the vocabulary now (the ADR-059
exception→trigger rename is the cautionary tale for loose naming):

- **Cohort definition** — registered once, like onboarding a pack. Stable id `cohort_def_id`
  (e.g. `wire_transfer_cohort`). Declares the correlation contract and the **end-of-process (close) message
  schema**. This is what a pack's membership points at.
- **Cohort instance** — spawned at runtime (e.g. `coh123`), bound to exactly one concrete
  **`correlation_value`** (e.g. `1v23p`). It is the observer that accumulates the member segment-instances
  sharing that value, and it is a **persisted state machine**.

Fixed terms: `cohort_def_id` (design-time), `correlation_key` (design-time — a dotpath into a member's trigger
envelope naming the tie field), `correlation_value` (runtime — the extracted value), `cohort_instance_id`
(runtime).

**Naming guard.** A runtime instance already carries a `correlation_id` (the OTel/trace correlation, defaulting
to `trigger_id` — see `ProcessInstance`). The cohort's `correlation_value` is a **different** concept and must
never be conflated with it in code or telemetry. Telemetry attributes use a distinct `amendia.cohort.*`
namespace.

### Membership (bottom-up, per-segment)

A pack gains an **optional** `cohort_membership` on its manifest:

```
cohort_membership:
  cohort_def_id: "wire_transfer_cohort"
  correlation_key: "exception_id"      # dotpath into THIS pack's trigger envelope
```

Membership is **per-segment** because members triage to different packs with different, domain-neutral trigger
schemas (ADR-047/049) — so each member maps *its own* trigger field to the cohort's correlation slot rather
than assuming a shared field name. A pack with no `cohort_membership` is unaffected (ordinary standalone
process). If a trigger arrives whose `correlation_key` field is **absent/null**, the segment still runs
normally and simply does not join a cohort (graceful non-membership). V1 allows **at most one** membership per
pack.

### Identity, dedup, and the global-uniqueness invariant

The cohort **instance** is identified and deduplicated by **`correlation_value` alone**. This rests on a
load-bearing V1 invariant: **`correlation_value` is globally unique across cohorts** — one value maps to
exactly one cohort instance (and therefore one `cohort_def_id`). This is what lets the external close message
carry only the value (below) and keeps Amendia's ids out of the external world.

- Dedup key = `correlation_value` (unique index). `cohort_def_id` is a stored attribute, set from the first
  member's membership.
- Get-or-create must be **atomic** — an idempotent `find_one_and_update(..., upsert=True)` keyed on
  `correlation_value`, first-writer-wins — because two segments with the same value can arrive concurrently.
  App-level check-then-insert would race.
- **Integrity guard:** if a later member arrives with an existing `correlation_value` but a *different*
  `cohort_def_id` in its membership, that is a contradiction of the invariant → flag it (log + a
  `late_join`-style anomaly event), do not silently re-home it.
- Member-join is **idempotent** on `process_instance_id` (a checkpoint-restarted segment must not
  double-register).

### Lifecycle — a persisted state machine closed by an external signal

An observer over externally-triggered, unbounded members cannot deterministically know it is "complete." So the
cohort does **not** guess completeness (no expected-member roster in V1). Instead, the **cohort definition
registers an end-of-process (close) message schema**; the external orchestrator emits that message when the
overall process ends, carrying the `correlation_value`. The cohort's state machine:

- `open` — created when its first member spawns; members accumulate.
- `closing` — the external close signal has arrived **while ≥1 member is still executing**. Per V1
  zero-authority, close does **not** terminate running segments; they run to completion and the cohort stays
  alive until the last active member reaches a terminal state. (Unlikely on the happy path, but handled.)
- `closed` — terminal; reached directly from `open` when no member is in flight at close time, or from
  `closing` when the last active member finishes.

State is **persisted** in the cohort SoR (Mongo) and every transition is durable, so an agent-runtime restart
mid-`closing` recovers exactly where it left off — the same crash-safe posture as instance checkpoints.

Edge cases (V1 dispositions):
- **Close with no open cohort** for its `correlation_value` (e.g. the whole case ran externally, or a
  close/first-segment race): benign, logged no-op.
- **A segment trigger after the cohort is `closed`** (late sibling): attach it to the existing closed cohort as
  a flagged `late_join`, surface it, and do **not** spin up a second cohort instance for the same value.

### Close-message ingress (recognising close vs trigger)

The close message enters through the **same front door** as triggers (`ingestor`). It must **not** triage to a
pack. Recognition is by the cohort definition's **registered close schema** — never by any leaked Amendia id
(the external system stays unaware that cohorts exist; it emits a normal "process ended" notification carrying
the business key). Recommended flow, reusing existing surfaces:

1. `ingestor` receives the inbound message and asks the registry to classify it (extend the existing
   `/resolve` step, or a sibling classify call).
2. The **registry** — which owns cohort definitions and schema knowledge — checks the payload against
   registered close schemas. On a match it returns a `cohort_close` classification with the
   `correlation_value` extracted via the definition's declared close-correlation path. Otherwise normal triage
   → pack resolution as today.
3. On `cohort_close`, `ingestor` publishes a `cohort_close_requested` event (instead of `trigger_dispatched`);
   **agent-runtime**, the owner of the cohort SoR/state machine, consumes it and drives `→ closing/closed` by
   `correlation_value`.

(Alternative considered: a dedicated agent-runtime close-intake endpoint. Rejected for V1 — it would split the
ingress front door and duplicate schema-matching that the registry already does.)

### Outbound segment→orchestrator notification (no cohort involvement)

Amendia also notifies the external orchestrator when a segment completes — but this is **nothing new and not a
cohort concern**: it is an ordinary activity backed by a send-message capability inside that segment's own BPMN.
The cohort emits nothing outbound; it stays strictly inbound-observing. This also closes the external-ordering
loop: a segment finishes → its capability notifies Pega → Pega fires the next segment's trigger (which joins the
same cohort by `correlation_value`) → … → Pega emits process-end → the cohort drains and closes. Amendia never
sequences; it observes the pieces it owns and lets the owner declare the end.

## Where it lives (component placement)

- **Cohort definition** — registered/queried in **process-registry** (new collection + repo + router;
  onboarding or a post-onboard step sets a pack's `cohort_membership`). Holds `cohort_def_id`, the
  close-message JSON Schema, and the close-correlation path.
- **Cohort instance SoR + state machine** — in **agent-runtime** (it spawns the first member and owns durable
  runtime state). New `cohort_instances` collection (unique index on `correlation_value`), repo, and a
  `CohortService` (get-or-open, join-member, advance-on-member-terminal, close).
- **Consolidation** — in **GLEA** (ADR-058), via a stamped correlation tag (below). The SoR holds identity,
  roster, and lifecycle; GLEA does the actual cross-segment consolidation for surfacing.

### The consolidation substrate (telemetry stamping)

Every segment instance already opens an OTel **root span** in `engine.start` via `start_instance_trace(attrs=…)`
and every node span re-parents to it (ADR-058), landing in ClickHouse `otel_traces`. We stamp the root span
(and thus the whole segment trace) with new conventions — `amendia.cohort.def_id`,
`amendia.cohort.instance_id`, `amendia.cohort.correlation_value` — so "show me everything for `coh123`" is a
single ClickHouse filter. GLEA groups by `cohort_instance_id`; the SoR is not on the read hot-path.

### GLEA surfacing (ADR-058-native)

- **`CohortLifecycleEvent`** — a sibling of `PackLifecycleEvent` in `amendia_contracts/governance_events.py`,
  emitted **fail-soft** by agent-runtime (mirroring `emit_pack_lifecycle`), carrying a `Trace`
  (`correlation_id` + `trace_id`). Ops: `opened`, `member_joined`, `closing`, `closed`, `late_join`. Kept
  **thin on purpose** — it emits only the cohort's **own** transitions; it does **not** re-emit member terminal
  outcomes, because the member instances already publish their own terminal telemetry. GLEA derives the
  member-status rollup by joining those on `cohort_instance_id`, so there is one source of truth for "did
  segment X succeed." (Fields stay structural/domain-neutral per the ADR-058 review gate — `correlation_value`
  is opaque data, not a business-term key.)
- **`cohort_instances` read-model** (ClickHouse) — one row per cohort instance: `cohort_def_id`,
  `correlation_value`, `opened_at`, `closed_at`, close outcome, `member_count`, and a running/done/failed
  rollup derived from the joined member outcomes.
- **Instance read-model** gains cohort columns so any instance is filterable/backlinkable by cohort.
- **UI (extends the ADR-058 phase-E instance view lineage):** a **cohort list** (active + closed,
  correlation_value, member count, rollup status); a **cohort detail** (the segment roster where each member
  links to its existing instance view, a consolidated cross-segment audit timeline, and the close event with
  its orchestrator-reported outcome); and — highest value, smallest cost — a **backlink on the instance view**:
  "part of cohort `coh123` (`wire_transfer_cohort`), N sibling segments."

## Consequences

- Segmented cross-system cases become observable as a unit in GLEA without changing how any segment executes,
  and without leaking Amendia identifiers to the external world.
- A new registered entity (cohort definition), a new runtime SoR + state machine (cohort instance), a new
  event type, a new ingress classification branch, and new GLEA read-models/views. Cross-service but additive —
  a pack with no `cohort_membership` and a deployment that registers no cohort behave exactly as today.
- The observability picture is honestly partial: Amendia can only show the segments it owns. The cohort detail
  should make the external segments' absence explicit rather than implying Amendia saw the whole process; the
  orchestrator's close outcome is the authority on overall completion.
- New load-bearing invariant (`correlation_value` globally unique) — see Assumptions.

## Scope boundaries (what V1 does NOT do)

- **No execution authority.** The cohort never sequences, gates, hands off state, or terminates segments.
  Ordering is external. Not a saga.
- **No completeness inference.** No expected-member roster; the external close signal is the sole terminator.
- **No stitched cross-process diagram.** Amendia does not own the external segments and will not draw them.
- **No outbound cohort messaging.** Segment→orchestrator notification is an ordinary in-segment capability.
- **No multi-cohort membership** per pack; **no** cross-`correlation_value` grouping (a cohort instance is
  per value).

## Assumptions

- **`correlation_value` is globally unique across cohorts** in V1 — it alone identifies a cohort instance and
  is sufficient to close it. A domain with non-unique correlation values (needing `(cohort_def_id,
  correlation_value)` addressing on the close path, which would force the external system to name the cohort)
  is a **V2 revisit**.
- All members sharing a `correlation_value` share one `cohort_def_id` (enforced by the integrity guard).
- The external orchestrator reliably emits the registered close message at end-of-process; if it never does, a
  cohort remains `open` indefinitely (acceptable for V1 — no TTL/auto-close).

## Phase plan (each phase its own CC prompt + report, per the build convention)

1. **Runtime foundation** — contracts (`CohortMembership` on the manifest; `CohortLifecycleEvent`/`Op`; the
   cohort-definition model), telemetry conventions, the `cohort_instances` SoR + `CohortService` state machine,
   join-on-spawn in `DispatchService`, root-span stamping in `engine.start`, member-terminal → drain advance,
   and the fail-soft lifecycle emit. Unit + e2e (two segments, same `correlation_value`, one cohort; dedup
   under concurrency; idempotent re-join).
2. **Definition registration + close ingress** — registry cohort-definition CRUD and membership assignment;
   ingress classification of close messages; the `cohort_close_requested` event and its agent-runtime consumer;
   the `open → closing → closed` drain and the late-join / no-open-cohort edges end-to-end.
3. **GLEA surfacing** — the `cohort_instances` read-model + instance-read-model cohort columns, cohort
   list/detail read APIs, and the webui cohort views + instance-view backlink.

The accompanying CC prompt implements **Phase 1** only, so each slice stays reviewable; Phases 2–3 get their own
prompts as the work lands.
