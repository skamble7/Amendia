# ADR-064 — Cohort SLAs: cross-system timing expectations, at-risk/breach detection, and accountability attribution

**Status:** Proposed — 2026-08-12
**Date:** 2026-08-12
**Context owner:** Sandeep Kamble
**Relates:** ADR-063 (Cohorts — observability grouping for segmented cross-system processes; definition vs
instance, `correlation_value` sole handle, zero execution authority, `open→closing→closed`, GLEA
`cohort_events`), ADR-027 (durable timer substrate — Mongo-backed poller, crash-safe park/fire), ADR-031
(event-based gateway timer arms), ADR-058 (GLEA observability on OTel + ClickHouse; the existing
`sla_breaches` audit metric), ADR-062 (precise per-member diagram highlighting), and the trust/accountability
business view (`amendia_trust_accountability_business_view.md`). Authoring guide:
`backend/docs/methodology/cohort_authoring_guide.html`.

## Context

ADR-063 gave Amendia **cohorts**: a way to group the segments of one larger cross-system case (an external
orchestrator such as Pega owns the overall flow and delegates some segments to Amendia) so they can be observed,
audited, and reported together. A cohort is a **pure observer** — it never sequences, gates, or terminates a
segment.

What a cohort cannot yet do is notice **time**. The original motivation for cohorts was precisely a cross-system
failure mode that is invisible today: *a segment that should have been invoked within a certain window never
starts because the external system never sent the trigger.* The larger process is stalled, but from Amendia's
event-driven view "nothing happened" is indistinguishable from "nothing was supposed to happen yet." Related
blind spots: the external system never sends the end-of-process **close** (the cohort sits `open` forever); the
gap between one segment's handback and the next segment's trigger drifts unboundedly; a segment Amendia *is*
running overruns; the whole case exceeds an end-to-end deadline.

These are **SLA violations in a multi-system process**, and crucially they can be owned by *either* side — the
external orchestrator (it never invoked us) or Amendia (our segment ran slow). Today no one is accountable
because no one is watching the clock across the seam. We want cohorts to watch that clock, warn **before** a
deadline slips, record the breach when it does, and **attribute** it — all without acquiring any execution
authority (a breach must never abort, force, skip, or synthesise a step; that would break the ADR-063 observer
contract and turn the cohort into a saga).

A key enabler already exists: agent-runtime has a **durable, crash-safe timer substrate** (ADR-027) — a
Mongo-backed poller that fires due timers and re-fires anything missed on restart. And GLEA already has an
`sla_breaches` metric (ADR-058). So this ADR is mostly about a **model** (how an author expresses timing
expectations) and a small, reused **mechanism** (scheduling + evaluation on the existing substrate), not new
infrastructure.

## Decision

Add **Cohort SLAs**: an observational timing-expectation layer declared on the cohort **definition** and
evaluated against the cohort **instance** at runtime. A breach **flags, warns, and attributes** — it never
enforces. Concretely:

### The SLA primitive (one shape for every scenario)

Every SLA is four parts:

> **After** an *anchor event*, **expect** a *satisfying event* **within** a *deadline* (duration + clock); if
> the deadline passes unmet, it is a **breach**, owned by an *accountable owner*.

A breach is simply: the deadline timer fires and the satisfying event has not been observed. This one primitive
expresses missing triggers, missing close, inter-segment gaps, segment overruns, and end-to-end deadlines — the
scenario is just a choice of anchor, satisfying event, and owner.

### The expectation graph (a DAG on the definition)

Timing expectations require knowledge an observer cannot infer — *which* segments are expected and in *what
order*. The author declares this as a **directed acyclic graph** on the cohort definition:

- **Nodes** = the cohort's member segments, plus two synthetic nodes: **Start** (the cohort opens on its first
  member) and **Close** (the external end-of-process message, per ADR-063's close schema).
- **Edges** = precedence expectations ("after this, expect that"). An edge from **Start** is an
  *independent window* anchored to cohort-open; an edge between two segments is a *sequential hop*. This makes
  the two declaration styles the same mechanism — independent windows are root-anchored edges — so there is one
  model, not two.
- **Split type** (a property of a node's out-edge set when it has more than one successor):
  - **AND** — all successor branches are expected (parallel work); a no-show on any is a breach.
  - **XOR** — exactly one successor is taken; when one arrives, its siblings are **voided** (never breach).
- **Node type**: **expected** (should always run) or **conditional** (only on some paths; belongs on an XOR
  branch). This is what tells Amendia whether a no-show is a fault or a branch not taken.

The DAG is an **expectation model, not an execution model** — Amendia never runs, sequences, or forces it. It
uses the DAG only to (a) schedule expectation timers and (b) resolve conditional skips. If the real external
flow diverges from the declared DAG, the resulting breaches are an honest measurement of that divergence (the
SLA is measured against the *declared contract*).

**Two clocks per node.** Each segment has two observable moments an SLA can target:
- **arrival** — the external system invoked the segment and Amendia started it -> an arrival SLA answers "did the
  trigger show up in time?" (owner almost always **external**);
- **completion** — the segment reached a terminal state inside Amendia -> a completion SLA answers "did our
  segment run fast enough?" (owner **Amendia**).

This split is the mechanism of attribution.

### Conditional resolution (no false alarms)

- **Expected** node: a missing arrival past its deadline is always a **breach** (owner: external). Only an
  explicit member failure or the cohort closing excuses it.
- **Conditional** node: the expectation is **voided** (not breached) the instant a *resolving event* proves the
  branch was not taken:
  - a **sibling on the same XOR split arrives** (the chosen alternative — this is why XOR siblings must be
    declared together, so Amendia knows what counts as "the other branch"); or
  - the **cohort closes** (the external close voids any still-pending expectation — this covers a conditional
    *last* segment: the close proves it wasn't needed).
  If no resolving event occurs and the deadline passes, a conditional node still breaches.

Voided != breached; a voided or satisfied expectation never fires an at-risk or breach signal.

### At-risk before breached

Each SLA carries a **deadline** and an earlier **at-risk lead** (e.g. breach at 4h, at-risk at 3h):
- crossing the at-risk threshold with the event still outstanding -> **at-risk** (amber): a warning + optional
  alert so ops can chase the responsible party *before* the promise is blown;
- crossing the deadline unmet -> **breach** (recorded, attributed).

At-risk is a chance to prevent; breach is a fact to record.

### Clocks: wall-clock and business hours

Per SLA, the author chooses **wall-clock** (real elapsed time — for machine-to-machine steps) or **business
hours** (measured against a configured business calendar of working hours + holidays — for steps that wait on
people, so an SLA does not "breach" overnight or across a weekend). Business-hours SLAs depend on a configured
calendar (a deployment-level config; V1 may ship a single default calendar).

### Attribution as a first-class field

Every SLA names an **owner** in {**external**, **amendia**, **shared**}. Arrival/gap SLAs -> external;
completion/runtime SLAs -> Amendia; end-to-end (Start->Close) -> shared. Breaches roll up by owner, turning the
cohort into a **cross-system accountability ledger** (the trust/accountability business view): "of the cases
that missed SLA this month, N were the orchestrator failing to invoke us, M were our own segments running slow."

### Mechanism — durable, crash-safe, exactly-once (reuse ADR-027)

- **Scheduling.** When a cohort instance opens (and as members arrive), agent-runtime materialises the pending
  expectations from the definition's DAG into **durable timer rows** (a new `cohort_sla` timer *kind* on the
  ADR-027 timer collection, or a sibling collection with the same poller). A row is roughly
  `{cohort_instance_id, sla_id, node/edge ref, anchor, satisfying_condition, due_at, at_risk_at, clock, owner, state}`.
- **Firing = evaluate & flag, not park & resume.** Unlike a BPMN timer (which parks an instance and resumes it),
  an SLA timer, when it fires, **reads cohort/member state and decides**: if the satisfying event has occurred ->
  resolve; else -> record a breach (emit a breach event, flip state to `breached`, raise the alert/anomaly).
- **Crash-safety.** Because `due_at` lives in Mongo, a service outage loses nothing: on restart the poller
  re-evaluates all pending timers and fires anything that came due while it was down. **Deadlines are detected
  late-but-never-missed.** Each breach is stamped with both `due_at` (when it *should* have breached) and
  `detected_at` (when we noticed), so reporting stays honest about downtime.
- **Cancel-on-satisfy.** When the satisfying event arrives in time — a member spawns (arrival), a member reaches
  terminal (completion), an XOR sibling arrives (voids), or the close lands (voids/terminates) — the same
  fail-soft join/close handlers that already run in agent-runtime **resolve the corresponding timer atomically**
  with the state update, so it never false-fires.
- **Exactly-once.** Firing is a conditional compare-and-set on timer state (`pending -> fired`), the same
  first-writer-wins / `finalize_if_drained` pattern ADR-063 already uses to guarantee exactly one `closed`. A
  late arrival *after* a breach fired leaves the breach standing but records "arrived late" (attribution keeps
  the truth).

### Where it lives (component placement)

- **Definition (the DAG + SLAs)** — **process-registry**, extending the ADR-063 `CohortDefinition`
  (today: `close_schema`, `close_correlation_path`, `close_outcome_path`, flat membership). Membership becomes
  the DAG: nodes (member refs + node type), edges (split type + optional SLA), and per-node runtime SLAs. Owner
  (`role.process.owner`) gated, like all cohort-definition writes.
- **Evaluation + SoR** — **agent-runtime**, which already owns the cohort instance SoR, the fail-soft join/close
  path, and the ADR-027 timer poller. SLA state (`pending | at_risk | satisfied | voided | breached`) is
  persisted per expectation on/next to the cohort instance; the authoritative timers are the durable rows.
- **Surfacing** — **GLEA**: a new `CohortSlaEvent` (sibling of `CohortLifecycleEvent`, ADR-058-native) carries
  at-risk/breach/resolve into a read-model that extends `cohort_events`, and feeds the existing `sla_breaches`
  audit metric with an owner breakdown. The agent-runtime SoR stays authoritative; GLEA is observability-grade.
- **UI (webui)** — authoring on the cohort *definition* detail (the ADR-063-followup inline-edit surface): a
  **tabular DAG + SLA editor** in V1 (nodes, edges, split type, node type, per-edge SLA fields), with a
  **visual DAG canvas deferred to a later phase**. Observability on the cohort *instance*: per-expectation
  at-risk/breached chips, countdowns to the next deadline, and breaches surfaced as anomalies; an owner-attributed
  SLA summary.

### Definition edits — forward-only (versioning deferred)

Editing a cohort definition's DAG or SLAs is **forward-only with a warning**, consistent with membership today:
changes affect cohort instances that **open after** the change; instances already running keep the expectations
(and timers) they started with — Amendia does not retro-apply new deadlines to an in-flight case. A warning is
shown when live instances exist. Full **version-pinning** (each instance bound to the definition version it
opened under) is explicitly deferred — it remains the open **CB-6** decision, now with more weight because the
expectation graph is higher-stakes to mutate mid-flight than a membership row.

## Consequences

- Cohorts gain **time-awareness and accountability** while staying pure observers — the headline value is
  cross-system attribution ("who was late"), not just alerting.
- The **absence of an expected event** becomes detectable (missing trigger, missing close) — the original
  motivating gap — via durable timers, with no new scheduling infrastructure and full crash-safety.
- Cohort **membership graduates from a flat set to a declared DAG.** This is a real authoring-surface increase;
  mitigated by (a) making SLAs optional per edge, (b) shipping a tabular editor before a visual one, and (c) the
  authoring guide.
- Breaches extend the **existing GLEA `sla_breaches`** surface with an owner dimension; no new audit substrate.
- **New failure-mode to design against:** a mis-declared DAG (divergent from the real external flow) produces
  misleading breaches. Framed as honest ("measured against the declared contract") and softened by at-risk
  warnings and forward-only edits, but the authoring guide must stress modelling only what you can observe.
- Poller load grows with the number of open cohorts x pending SLAs; bounded (SLAs resolve/void as a case
  progresses) and the poller already scans due timers, but worth watching at scale.

## Scope boundaries (what V1 does NOT do)

- **No execution authority.** A breach flags/warns/attributes only — never aborts, forces, skips, retries, or
  synthesises a segment or a trigger. (Preserves ADR-063.)
- **No loops / repeating segments** and **no runtime-dynamic branching** the author can't enumerate. Known
  alternatives are modelled as XOR; a truly unpredictable segment is left out of the graph (runs standalone).
- **No outbound "you're late" nudge** to the external system in V1 (a segment->orchestrator notification is an
  ordinary in-segment capability per ADR-063; an SLA-driven outbound is a possible V2, opt-in).
- **No visual DAG canvas** in V1 (tabular editor first).
- **No definition version-pinning** (forward-only-with-warning; CB-6 stays parked).
- **No business-calendar authoring UI** in V1 if it proves heavy — a single deployment-configured calendar is
  acceptable for the first cut.

## Assumptions

- The **ADR-027 timer substrate** can carry a new timer kind whose fire-action evaluates state rather than
  resuming an instance (it already supports multiple kinds, incl. the ADR-031 gateway arm).
- `correlation_value` remains the **sole handle** and globally unique (ADR-063 V1 invariant); SLAs are scoped to
  a single cohort instance.
- The set of member segments and the observable arrival/completion moments are sufficient anchors; SLAs never
  require visibility into the external system's internal steps.
- A business calendar (working hours + holidays) is available as config for business-hours SLAs.

## Phase plan (each phase its own CC prompt + report, per the build convention — backend before frontend)

1. **P1 — Definition model + validation (process-registry).** Extend `CohortDefinition` with the expectation
   DAG (nodes, edges, split type AND/XOR, node type expected/conditional) and per-edge/per-node SLA specs
   (anchor, satisfying, deadline, clock, at-risk lead, owner). Well-formedness validation: acyclic, single Start,
   Close reachable, XOR/AND consistency, every conditional on an XOR branch, owner/clock enums. Reuse the
   owner-gate and the create/`PUT` inline-edit endpoints (ADR-063 follow-up); forward-only edit semantics.
2. **P2 — Runtime scheduling + evaluation (agent-runtime).** Materialise pending expectations into durable
   `cohort_sla` timers on cohort open / member arrival; fire = evaluate-and-flag; cancel-on-satisfy wired into
   the existing fail-soft join/close handlers; XOR-sibling and close voiding; at-risk->breach transitions;
   exactly-once compare-and-set; `due_at`/`detected_at` stamping; crash-safe re-fire on restart. Persist
   per-expectation SLA state on the cohort instance.
3. **P3 — GLEA surfacing.** `CohortSlaEvent` + `cohort_events` read-model extension; owner-attributed
   `sla_breaches` rollup; endpoints for a cohort's SLA state (pending/at-risk/breached with due/detected times
   and owner).
4. **P4 — webui.** Tabular DAG + SLA editor on the cohort-definition detail (owner-gated, forward-only warning);
   at-risk/breached chips + next-deadline countdown + breach anomalies on the cohort instance; owner-attributed
   SLA summary. (Visual DAG canvas: later.)

Each phase is verified against the code before the next prompt is written; the authoring guide
(`cohort_authoring_guide.html`) is kept in sync as the implementation firms up the exact field names and editor
shape.
