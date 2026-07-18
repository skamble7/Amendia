# ADR-031 — Message correlation + event-based gateway (Common-Executable ladder rung 3)

**Status:** Accepted · **Date:** 2026-07-17 · **Builds on:** ADR-027 (BPMN conformance / execution
profiles), ADR-029 (timer substrate — this rung's sibling), ADR-030 (error boundary / unified
boundary channel), Phase 2.5 (per-pack profile pin + load guard).

## Context

**Rung 3 of the Common-Executable ladder** — the next real *substrate*: inbound business messages
waking a parked instance (a counterparty answering an RFI, a long-running external screening calling
back). It mirrors the timer substrate (ADR-029). Its capstone, the **event-based gateway**, falls out
by composing the (already-built) timer arm with the new message arm.

**Two locked decisions:**
- **Intake = an HTTP endpoint on agent-runtime.** Any source (external system, `mcp_stub`, operator,
  tests) POSTs a message; the runtime correlates and resumes.
- **Correlation = business anchor.** A message references `exception_id` (or `correlation_id`) + a
  message name → the waiting instance's subscribed element. No internal-instance-id leakage, no
  per-pack correlation expressions/properties.

## Decision

**Native durable substrate, sibling of the timer substrate.**

- **Subscriptions.** A durable `message_subscriptions` collection (unique `(instance, element)` →
  idempotent re-register on crash replay; indexed by `(message_name, exception_id)` /
  `(message_name, correlation_id)` for delivery lookup). A new **`WAITING_MESSAGE`** instance status —
  a durable, crash-safe park parallel to `WAITING_TIMER` / `WAITING_HITL`; the recovery sweep leaves
  it alone, a delivery resumes it. A `MessageSubscriptionService.register/find_match/cancel`.
- **Intake.** `POST /messages` — `{message_name, exception_id?|correlation_id?, payload?}`, guarded by
  `principal_or_internal` (external callers use `X-Amendia-Internal`, operators a bearer). It
  correlates to a **pending** subscription and resumes that element under the **same guarded
  `WAITING_*→RUNNING` first-wins** serialization the timer race uses. Responses: `202` delivered,
  `404` no_matching_subscription, `409` already_consumed, `422` invalid payload. A thin
  `message_received` event (ids/labels only — no payload) is published for observability.
- **Ordering race.** An inbound message with no matching subscription is persisted in a TTL'd
  `pending_messages` buffer; when a subscription registers (`_park_message`), it checks the buffer
  first and delivers immediately — a fast external caller never loses the race. (The POST still
  reports `404` at that instant; the buffered message is delivered on registration.)
- **Constructs.** `messageIntermediateCatchEvent` and `receiveTask` compile to nodes that interrupt on
  entry → the engine registers a subscription and parks `WAITING_MESSAGE`; on delivery the node
  resumes and proceeds. The **event-based gateway** interrupts on entry → the engine registers **all
  arms** (a timer per timer-catch, a subscription per message-catch); the **first arm to fire wins**,
  its branch proceeds, and the **losers are cancelled** (`TimerService.cancel_gateway_arms` /
  subscription `cancelled`) under the same guarded transition. This is the reference "await screening
  result vs timeout" pattern, reusing both substrates + the first-wins machinery.
- **Typed vs signal payload (additive binding).** A message binding is `{executor: {type:"message",
  message_name}, element_kind: "messageCatch"|"receiveTask"}` with **optional** `outputs`. If an
  output artifact is declared, the delivered payload is **validated against the pinned schema and
  committed as that artifact** (reusing the artifact-write validation — a malformed payload fails the
  *delivery* with `422`, never commits, instance stays parked); if absent, the message is a pure
  signal recorded untyped in a `messages` state channel. HITL/inputs are not required for this
  executor. The registry **bijection extends** to message catch/receive elements (a message binding
  requires `message_name`; a declared output must resolve).
- **Profile.** `messages` is appended to `EXECUTION_PROFILES` as the next **cumulative** rung (above
  `error_boundary`). `required_profile(model)` returns it when the executable core has a message
  catch / receive task / event-based gateway; Phase-2.5's derived pin + load-time `>=` guard carry
  over. Default stays `common_subset`.

## Crash-safety / exactly-once

Subscriptions + the pending buffer + the graph checkpoint are all durable. On restart the sweep leaves
`WAITING_MESSAGE` parked; a delivery (or a buffered message) resumes it; the subscription flips
`consumed` only after the resume segment succeeds, and the instance-status guard makes a re-delivery a
safe `already_consumed` no-op — exactly-once resume.

## Consequences

- An inbound business message correlates by business anchor + name to a parked instance and resumes it
  exactly once, race- and crash-safe, with an ordering buffer. The reference "await result vs timeout"
  event-gateway pattern runs end to end.
- One unified boundary/first-wins model now spans timer, error, and message/event constructs.
- **Dev delivery:** drive the pattern with e.g.
  `curl -H "X-Amendia-Internal: $TOKEN" -H 'content-type: application/json' \`
  `  -d '{"message_name":"rfi_reply","exception_id":"EXC-123","payload":{"answer":"yes"}}' localhost:8083/messages`.

## Deferred / non-goals

- **Message throw / send tasks (outbound)** — already modeled as side-effectful capabilities (e.g.
  `notify_parties`); this rung is inbound only.
- **Signal / escalation events, message *start* events, full BPMN correlation properties/expressions**
  (business-anchor only, per the decision), typed message-payload transforms.
- Real per-arm typed-payload commit on **event-gateway** message arms (event-gateway arms are routing
  signals this rung; standalone catch/receive support typed commit).
- No concurrent human gates; no default-profile change. Cumulative-linear-rank assumption per
  ADR-029/030 still holds — the levels will likely collapse to a single `common_executable` alias once
  the construct set is complete.
