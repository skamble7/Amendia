# ADR-019 — Capability memoization, contract-derived egress policy, and OpenShell integration findings (Phase 3)

- **Status:** Accepted (Part A + Part C). Parts B, D, E were **blocked** by the finding below and are
  now **resolved in ADR-020** (transport inverted → in-sandbox capability-worker over the broker).
- **Date:** 2026-07-10
- **Related:** ADR-011 (pure/sync nodes, HITL replay), ADR-016 (**trap 2** — `review_after` re-runs
  the capability on resume), ADR-017 (the `native`/`nemoclaw` mode, the `OpenShellClient` seam, the
  `SandboxedExecutor` memo seam, the `[confirm]` list this resolves), ADR-018 (the `nemoclaw` polyllm
  provider + the `inference.local/v1` proxy), `amendia_secure_runtime_nemoclaw_plan.md` §7–§10.
- **Advances:** delivers Phase 3's **memoization** (fixing trap 2) and **contract-derived egress
  policy**, and records the **confirmed** OpenShell wire facts — while documenting a blocking
  architectural finding that changes Parts B/D/E from "implement the client" to "pivot the design."

## Context

Phase 3 set out to (A) memoize capabilities per instance, (B) implement the real
`HttpOpenShellClient`, (C) derive egress/tool policy from contract data, (D) route real MCP sanctions
screening through the gateway, and (E) sandbox side-effect skills — all **against confirmed NemoClaw /
OpenShell docs**, with an explicit guardrail: *do not invent wire formats; if a shape/endpoint/auth is
not confirmable, STOP and surface the gap.*

Parts A and C are host-side and gateway-independent; they are delivered. Parts B/D/E depend on a
host→gateway execution API. Investigating the real product to confirm that API produced a decisive
negative finding (§Findings) that the guardrail requires we surface rather than paper over.

## Decision

### Part A — per-instance capability memoization (delivered; fixes ADR-016 trap 2 / ADR-017 trap 5)

`app/engine/executor/memo.py` adds a memo keyed on
**`(process_instance_id, element_id, inputs_hash, attempt)`**, persisted to a runtime-private Mongo
collection `capability_memo` (`MongoMemoStore`; `InMemoryMemoStore` for tests). `memoized_execute` is
the shared entry-point helper both `InProcessExecutor` and `SandboxedExecutor` call: **hit** → return
the memoized outputs without invoking the capability/model; **miss** → execute, then upsert
(idempotent) before returning. Only `execute`-mode invocations that produce `outputs` are cached
(`propose` is never cached). The host owns the store; the sandbox never writes it (ADR-017 trap 2).

The **`attempt`** component is the key insight that makes this correct under LangGraph's
replay-from-top model. The `process_instance_id` reaches the executor via the LangGraph-injected node
`config` thread id (no graph-state change → `native` stays byte-for-byte). The reject → re-run loop
increments `attempt`, and because LangGraph deterministically **replays** that loop on every later
resume, the reconstructed `attempt` makes replays hit the memo while a genuine reject (a new attempt)
is a real miss:

| Event | `_produce_outputs` call | attempt | memo | model called? | committed |
|---|---|---|---|---|---|
| initial run | pre-loop | 0 | miss → store A | yes | — (gate) |
| resume: **approve** | pre-loop | 0 | **hit A** | **no** | **A (reviewed)** |
| resume: **reject** | pre-loop / loop | 0 / 1 | hit A / miss → store B | once (B) | — (gate) |
| resume: **approve** after reject | pre-loop / loop | 0 / 1 | hit A / **hit B** | **no** | **B (reviewed)** |
| resume: **edit_and_approve** | pre-loop | 0 | hit A | no | **human edit** (via decision path; memo not consulted) |

Gating: memoization is **on by default in `nemoclaw`** mode and, in `native`, when
`AGENTRT_MEMOIZE_CAPABILITIES=true`; it is only effective when a memo store is wired (`main.py` wires
the Mongo store; with no store `native` is byte-identical). ADR-016 trap 2 / ADR-017 trap 5 are
**fixed** when memoization is enabled.

### Part C — egress/tool policy derived from contract data (delivered)

`app/engine/executor/policy.py::derive_egress_policy(descriptor)` builds an `EgressPolicy` purely from
the descriptor — no parallel hand-maintained list:
- **`mcp`** → host parsed from `runtime.endpoint` (self-descriptive, ADR-024) + `runtime.tools` whitelist + `transport`.
- **`llm`** → the managed inference proxy host `inference.local` (**confirmed**, ADR-018).
- **side-effect `skill`** → endpoint keys declared in `config_schema` (dev → stub only); read-only
  skills → minimal egress.

It is attached to `CapabilityRunSpec.egress_policy` (replacing the Phase-1 `None` placeholder) for
auditability and sandbox provisioning; the deterministic fake ignores it. Unit-tested per kind.

**Enforcement reality (confirmed):** OpenShell enforces egress at **sandbox-creation time** (CLI
`openshell policy set`, provider/MCP registration during `nemoclaw onboard`), **not** as a per-request
field — because there is no per-request execute API (§Findings). The derived allowlist is what would
feed sandbox provisioning.

## Findings — the OpenShell integration reality (resolves ADR-017's transport `[confirm]`)

Confirmed against the live NVIDIA OpenShell + NemoClaw docs, both GitHub READMEs
(`NVIDIA/OpenShell`, `NVIDIA/NemoClaw`), the `docs.nvidia.com/{openshell,nemoclaw}/llms.txt` indexes,
the CLI/quickstart pages, and an independent hands-on walkthrough:

**Confirmed facts (ADR-017 `[confirm]`s now retired):**
- Managed inference proxy: OpenAI-compatible at **`https://inference.local/v1`** (in-sandbox;
  NemoClaw writes `/sandbox/.deepagents/config.toml`). *Retires ADR-017's inference-proxy `[confirm]`
  and confirms ADR-018's seed.*
- OTLP: traces are **exported** to a collector at **`http://host.openshell.internal:4318/v1/traces`**
  (service `nemoclaw-langchain-deepagents-code`) — asynchronous export, not a synchronous
  trace-id-in-response.
- MCP: a **file-based registry** `/sandbox/.deepagents/.nemoclaw-mcp.json`, populated via
  `nemoclaw <sandbox> mcp add` (HTTPS-only definitions, OpenShell credential placeholders).
- Sandbox lifecycle, egress policy, and provider/credential scoping are **CLI-driven** at creation
  time (`nemoclaw onboard`, `openshell sandbox create`, `openshell policy set`); providers are
  injected into the sandbox as env vars; real secrets stay gateway-side (scoped placeholders).
- Execution is by the **in-sandbox** Deep Agents agent `dcode` (headless: `dcode -n "<prompt>"`).

**The blocking gap:** OpenShell/NemoClaw exposes **no host→gateway synchronous "execute a capability,
return artifact JSON + trace id" RPC.** ADR-017's `SandboxedExecutor → OpenShellClient.run_capability
→ HTTP gateway` shape (and the design doc's "execute RPC → artifact JSON", §3/§5.2, transport
`[confirm]`) assumed such an endpoint. **It does not exist.** Implementing `HttpOpenShellClient`,
gateway MCP brokering (Part D), or routing side-effect skills through the client (Part E) as HTTP calls
would require **inventing** the request/response shape, auth, and endpoints — which the Phase-3
guardrail explicitly forbids. Per that guardrail we **STOP** here and surface the gap.

`HttpOpenShellClient` is therefore left **guarded** (`ping` → unreachable; `run_capability` → raises
with the finding); the deterministic `FakeOpenShellClient` remains the only supported path and the CI
default. **Parts B, D, E are not delivered**, pending the design pivot below.

### Recommended pivot (for a follow-up ADR / decision)

OpenShell's model is "provision a governed sandbox, run an agent **inside** it." The faithful Amendia
integration is therefore **not** a host RPC but one of:
1. **Run agent-runtime's capability execution inside an OpenShell sandbox** — point `run_real_llm` at
   the in-sandbox proxy `https://inference.local/v1` (already an ADR-018 `nemoclaw` ref), resolve MCP
   via the in-sandbox registry, and let sandbox-creation policy (from Part C's derived allowlist)
   govern egress. The host still checkpoints; the sandbox still only returns data. OR
2. **A thin Amendia-owned sidecar** co-located in the sandbox exposing a minimal execute endpoint that
   *we* define (not a NemoClaw API) — an explicit Amendia contract, deployed via `nemoclaw onboard`.

Either is a real architecture decision that changes the ADR-017 seam's transport assumption; it should
be its own ADR, not a guessed wire format.

> **Resolved (ADR-020):** the pivot chosen is a variant of option 1 — an Amendia **capability-worker**
> runs *inside* the sandbox and **consumes** execution jobs from RabbitMQ (egress), publishing results
> back; the host never calls in. The `OpenShellClient.run_capability` seam is preserved (implementation
> swaps to `BrokerOpenShellClient`), and B/D/E are realized in the worker. See ADR-020.

## Consequences

- **Trap 2 is fixed** (memoization) and **egress policy is contract-derived** — both delivered,
  unit-tested, and `native`-safe (flag off ⇒ byte-identical). This is real, shippable Phase-3 value.
- **The `nemoclaw` execution path remains fake-only.** No regression: fake stays the CI default;
  `native` unchanged. Parts B/D/E await the pivot.
- **ADR-017 updates:** the inference-proxy and OTLP-endpoint `[confirm]`s are **retired** (confirmed
  above); the "gateway execute RPC transport" `[confirm]` is **resolved to: does not exist — pivot
  required**; the "real `HttpOpenShellClient`" item moves from "deferred, will implement" to "blocked,
  redesign."
- **Config added:** `AGENTRT_MEMOIZE_CAPABILITIES` (default False), `AGENTRT_OPENSHELL_TOKEN` (gateway
  auth *ref*, unused until the pivot), `AGENTRT_OPENSHELL_IT` (integration-test gate), `MEMO_COLLECTION`.
- **Compose/integration tests for a real gateway/MCP are NOT added** — there is no confirmed gateway
  API to stand up or test against. Adding a stub "gateway" would test a fiction. The env-gated
  integration-test switch (`AGENTRT_OPENSHELL_IT`) is in place for when the pivot lands.

## Traps recorded for maintainers

1. **Memo key must include `attempt`.** Dropping it breaks the reject → re-run case: replays would hit
   a stale entry and the reviewed artifact would not commit. The attempt is reconstructed
   deterministically by LangGraph's replay — that is *why* it works.
2. **Memoize `execute` only, and only when `outputs` are produced.** Never cache `propose`
   (approve_actions pre-gate) — it produces `proposed_actions`, not a committed artifact.
3. **Host owns the memo.** It is a runtime-private Mongo collection, scoped by
   `process_instance_id`; one instance never reads another's. The sandbox never writes it.
4. **`native` stays byte-for-byte.** Memoization is off by default in `native`; the memo store is only
   *used* when enabled. The node's added `config` parameter is injected by LangGraph and unused when
   memoization is off.
5. **Do not implement `HttpOpenShellClient` by guessing.** OpenShell has no host→gateway execute RPC
   (confirmed). Resolve the pivot (its own ADR) before writing any real client; until then the fake is
   the only supported `nemoclaw` path.
6. **Egress enforcement is creation-time, not per-request.** The derived `EgressPolicy` feeds
   sandbox provisioning (`openshell policy set` / `nemoclaw onboard`), not a per-call field.
