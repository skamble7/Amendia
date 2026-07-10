# ADR-015 — Real-time HITL dashboard: notification-service + SSE push (retire polling)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-009/ADR-011 (agent-runtime foundation + execution — the producer of the events this
  consumes), ADR-013 (auth frontend — the `live.ts` polling seam + the token bridge this reuses),
  `amendia_platform_contracts_v1.md` (contract 4 dispatch, 5 HITL — the event shapes), the
  agent-runtime execution pipeline reference (`amendia_agent_runtime_execution_pipeline.md`).
- **Advances:** the "SSE/notification-service push fan-out" deliberately deferred by ADR-011 and ADR-013
  (live surfaces "still poll through `src/api/live.ts`").

## Context

The agent-runtime already publishes a durable RabbitMQ event at **every** process state transition
(`dispatch_accepted`, `hitl_task_created`, `hitl_task_decided`, `process_completed`, `process_failed`;
plus the ingestor's `exception_dispatched` and the stub's `exception_raised`). Nothing consumed them for
the UI. The webui learned about state changes only by **polling** every live surface (`inbox`, task,
instances, exceptions) via TanStack Query `refetchInterval` (~4s) — laggy, chatty, and not production-grade.

Two concrete symptoms motivated this:
1. **Stale dashboard after actions.** Approving a HITL task didn't advance the "Progress" stepper until a
   full re-login. Root cause was twofold: the poll latency, *and* a derivation bug — `ContextRail` pinned
   the "current" step to the *task being viewed* (`currentElementId: task.element_id`) rather than the
   instance's live gate, so it could never advance even when fresh data arrived.
2. **No push transport.** The `notification-service/` directory existed but was empty; the contracts even
   carried a comment anticipating it ("*Thin HITL events (fanned out to the UI by the notification
   service)*"), and `live.ts`'s own docstring promised the transport swap would be localized to that module.

## Decision

### Part A — a dedicated `notification-service` (`:8088`)

A new stateless FastAPI service (`backend/services/platform/notification-service/`, mirroring the identity
scaffold; no database). It consumes the domain events and fans them out to browsers over **Server-Sent
Events**. Three pieces:

- **Broadcast consumer** (`app/events/consumer.py`) — adapted from `ingestor/reply_consumer.py`, with the
  one deliberate divergence that is the point of the service: it declares a **per-instance server-named
  `exclusive`, `auto_delete` queue** (`declare_queue("", exclusive=True, auto_delete=True)`) bound to the
  seven event routing keys. Every *other* consumer on the platform uses a durable *named* queue
  (competing-consumers / work-queue); here each notification-service process must receive **every** matching
  event to fan out to its own connected browsers. A durable named queue would round-robin events across
  replicas and browsers would miss half — hence the divergence, called out prominently in the module docstring.
- **Fan-out hub** (`app/hub.py`) — an in-process async pub/sub. The consumer callback non-blocking-offers
  each signal to every subscriber's bounded `asyncio.Queue`; a client that falls too far behind has its
  backlog **collapsed to a single `resync` signal** (the browser then re-fetches everything) so one slow
  client can never block the consumer. Single-process fan-out only; multi-replica needs a shared bus (Redis)
  — deferred.
- **SSE endpoint** (`app/routers/stream.py`) — `GET /stream`, guarded by `current_principal` (any valid
  bearer; **no role**, because signals are thin — see Part B). Streams `data:` frames, a `: ping` heartbeat
  every `HEARTBEAT_SECONDS`, and an initial `event: ready`. The request-id middleware is **pure ASGI** (not
  `BaseHTTPMiddleware`, which buffers the body and breaks long-lived SSE). **18 tests** (signal-mapper leak
  checks, hub fan-out + slow-client collapse, consumer→hub, auth-gated stream).

### Part B — thin-invalidation model (the security boundary)

SSE messages carry only **signals** — `{type, exception_id?, process_instance_id?, task_id?,
element_id?, role?, outcome?}` — projected by `app/events/signal_mapper.py`, which whitelists id/label
fields and **never** copies payload data (`decision`, `comment`, `edits`, `trace`, `reason`, capability
outputs). The browser uses a signal only to decide which TanStack Query keys to invalidate; the actual data
is re-fetched through the **existing role-guarded REST endpoints**. Consequences: authorization stays
entirely at the REST layer (the broadcast stream needs authentication only, not per-event role checks); a
missed/duplicated/replayed signal can never leak or corrupt data — worst case is a slightly delayed refetch,
caught by the resync-on-reconnect.

### Part C — webui: swap polling for SSE (localized to `live.ts`)

- **`api/notificationsStream.ts`** — a hand-rolled `fetch`-based event stream (native `EventSource` can't
  send an `Authorization` header). It reuses the OIDC **token bridge** (`authToken.ts`: `token/renew/
  onAuthLost`) and mirrors the API client's `401 → renew → retry` cycle, with capped-backoff auto-reconnect.
- **`api/signalToKeys.ts`** — maps a signal → query keys (prefix keys, since filters are embedded in list
  keys). **`app/NotificationsProvider.tsx`** owns the single connection: invalidates the mapped keys per
  signal, and on every (re)connect invalidates the full live-key set to resync anything missed.
- **`api/live.ts`** (the seam) — `usePollingQuery` now derives cadence from SSE health: **up → a slow ~60s
  safety poll; down/connecting → a fast ~5s fallback** so the app still works if the stream is unavailable;
  `intervalMs: false` stays one-shot. Signatures are unchanged, so **no feature `queries.ts` file changed**.
  The default 4s poll is gone.

### Part D — the stepper fix (rides along)

`ContextRail` now derives the current step from the instance's **live** open/claimed gate (mirroring
`InstanceDetailPage`), not the viewed task. With SSE invalidating `["instance", id]`, the Progress bar
advances the instant a decision lands — no re-login.

### Part E — deploy

Compose service (broadcast queue on RabbitMQ, auth env, healthcheck) + `webui.depends_on`; the Vite dev
proxy and nginx both gain `/api/notifications` (nginx needs `proxy_read_timeout 3600s` — buffering-off and
HTTP/1.1 keep-alive were already server-wide).

## Consequences

- **Real-time, for every operator, without polling.** Verified live: connecting authenticated, driving one
  AC01 exception pushed `exception_raised → exception_dispatched → dispatch_accepted → hitl_task_created`
  down the stream in order; the queue is `exclusive/auto_delete`; `/stream` 401s without a bearer; signals
  carry only ids/labels. The Progress stepper advances on approval with no re-login.
- **The transport swap was localized** to `live.ts` + one new provider exactly as ADR-013 promised; feature
  screens are untouched. Polling remains only as a graceful fallback.
- **Deliberately deferred:** multi-replica fan-out (in-process hub → Redis/shared bus); per-activity
  streaming granularity (a new per-node runtime event) — the existing lifecycle events already bracket every
  instance state change and the client refetches the full instance, so the dashboard is always correct at
  every gate/decision/completion, just not animated node-by-node through autonomous bursts;
  Last-Event-ID replay (the resync-on-reconnect covers gaps); role-scoped event filtering (not needed under
  the thin-signal model).
- **Traps recorded for maintainers:**
  1. **Broadcast queue** must stay `exclusive=True, auto_delete=True` — a durable named queue silently
     breaks fan-out across replicas.
  2. **Request-id middleware must be pure ASGI**, not `BaseHTTPMiddleware`, or the SSE body buffers and never
     flushes.
  3. **SSE auth is fetch-based** because `EventSource` can't set headers; the long-lived stream outlives a
     token, so the `401 → renew → reconnect` loop is load-bearing.
  4. The **signal mapper is the security boundary** — it must keep projecting a whitelist; never widen it to
     copy payload fields.
