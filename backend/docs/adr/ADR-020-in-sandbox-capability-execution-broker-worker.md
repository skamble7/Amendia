# ADR-020 — In-sandbox capability execution via a broker-driven capability-worker (Phase 3b)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-011 (pure/sync nodes, host-owned checkpoint/HITL), ADR-016 (polyllm/ConfigForge,
  the `_run_blocking` bridge, secret-refs), ADR-017 (the `native`/`nemoclaw` mode, the `OpenShellClient`
  seam, `CapabilityRunSpec`/`SandboxResult`, the fake), ADR-018 (`nemoclaw` provider →
  `inference.local/v1`), **ADR-019** (memoization; contract-derived egress; the finding that OpenShell
  has **no host→gateway execute RPC**), the design doc `amendia_secure_runtime_nemoclaw_plan.md` §3/§5/§9,
  and the project brief architectural decision 2 (*the agent runtime consumes work from RabbitMQ rather
  than being called in-process over HTTP*).
- **Advances:** resolves ADR-019's blocking gap by **inverting the transport** — makes the `nemoclaw`
  path real (retiring fake-only) and lands the previously-blocked B/D/E inside an in-sandbox worker.

## Context

ADR-019 confirmed against the live NVIDIA OpenShell/NemoClaw docs that an OpenShell sandbox is
**egress-oriented**: it reaches *out* to `inference.local/v1` (managed inference), to MCP servers via an
in-sandbox file registry (`/sandbox/.deepagents/.nemoclaw-mcp.json`, `nemoclaw … mcp add`), and to OTLP
at `host.openshell.internal:4318/v1/traces`; egress allowlist + credential scoping are set at
**sandbox-creation time** via CLI (`openshell policy set … policy.yaml`). Inbound serving to a sandbox
is **not** a documented first-class feature (re-confirmed here — the README describes only "minimal
outbound access … opened with a short YAML policy the proxy enforces"). So the ADR-017
`HttpOpenShellClient` (host→sandbox HTTP) cannot exist.

**The fix is to invert the transport.** Instead of the host calling into the sandbox, an Amendia
**capability-worker** runs *inside* the sandbox and **consumes** execution jobs from RabbitMQ (egress)
and **publishes** results back. This is squarely the project's "consume work from RabbitMQ, not
in-process HTTP" decision, applied one level down — to capability execution.

Crucially this **preserves the ADR-017 seam**: `OpenShellClient.run_capability(spec) -> SandboxResult`
is unchanged; its implementation swaps from the dead HTTP scaffold to a **broker request/reply** client.
`SandboxedExecutor`, `CapabilityRunSpec`, `SandboxResult`, the fake, memoization (ADR-019), and the
contract-derived egress policy (ADR-019) all carry over.

## Decision

### Part A — one shared execution core (`executor/core.py`)

The kind-dispatch (`skill` / `llm` via `run_real_llm` / `mcp` / simulation) was extracted from
`InProcessExecutor` into `execute_capability(descriptor, inputs, ctx, *, mcp_client=None)`. Both the
in-process path **and** the worker call it, so they are behaviourally identical by construction.
`InProcessExecutor` (native) now just runs the core in-process with `mcp_client=None` → mcp sim-fallback,
exactly as before (**native byte-for-byte**, verified). The core does no validate/commit/memo/HITL —
those stay host-side (ADR-017 trap 2).

### Part B — the capability-worker + broker client (the substrate)

- **`capability-worker`** (`backend/services/agent-runtime/worker/`): a RabbitMQ consumer that binds a
  durable queue to `agent_runtime.capability_exec_request.v1` (competing consumers — scale by count),
  runs each job through the shared core (off the event loop via `to_thread`), and publishes the
  correlated reply to the requester's `reply_to`. It carries **no** Mongo/checkpoint/HITL — raw outputs
  only. It is a **plain process** in dev/CI (`python -m worker.main`); OpenShell is a deploy layer.
- **Broker request/reply** (`amendia_common.events`: `capability_exec_request` / `capability_exec_result`
  on `amendia.events`). The host publishes `{request_id, spec}` and awaits the correlated reply.
  - **Correlation** by `request_id` = `(process_instance_id, element_id, inputs_hash, memo_attempt)` →
    **idempotent** under redelivery (a duplicate maps to the same id) and composes with the ADR-019 memo
    (a memo hit never even publishes a job).
  - **Timeout** from `constraints.timeout_seconds`; **retry** only if `idempotent` (mirrors the host
    retry policy); a timeout / worker-error is surfaced as a `CapabilityError` → the node fails
    deterministically (never swallowed).
  - **Secrets never cross as values** (ADR-017 trap 3): the job carries the model-config **ref** +
    descriptor (refs only) + inputs + output schema — no keys. Inference creds are brokered by OpenShell.
- **`BrokerOpenShellClient`** implements `OpenShellClient` over a `BrokerTransport`:
  `InMemoryBrokerTransport` (drives the worker runner in-process — the CI/unit substrate, no RabbitMQ)
  and `RabbitBrokerTransport` (real aio-pika RPC, per-call connection because `_run_blocking` runs each
  call on a fresh loop; env-gated integration). Selected in `nemoclaw` mode when
  `AGENTRT_CAPABILITY_WORKER_ENABLED`; **the fake stays the default when unset** (CI unchanged).
- **`HttpOpenShellClient` is retired** — kept guarded (raises) with a pointer here; never selected.
- **Host still owns everything trusted**: after the worker returns outputs, the host runs the existing
  `_validate`, commits, appends `actor_log` (with the worker's OTLP trace id), checkpoints, and
  reads/writes the memo. None of that moved into the worker.

### Part C — B/D/E, realized inside the worker

- **(B) LLM → `inference.local/v1`.** The worker runs the core's `run_real_llm` with the selected
  `nemoclaw` ref (base_url `inference.local/v1`, ADR-018); creds brokered by OpenShell (no raw key held).
  Dev/CI point `AGENTRT_WORKER_INFERENCE_BASE_URL` at a stub OpenAI-compatible endpoint (no GPU/NIM).
- **(D) Real MCP.** `executor/mcp_client.py`: `HttpMcpClient` POSTs a standard MCP `tools/call` to the
  capability's self-descriptive `runtime.endpoint` (ADR-024 — no `server_key`/registry indirection) over
  `streamable_http`; `StubMcpClient` is the deterministic dev/CI double (marker-based, `list_provider`
  stays stub — no real OFAC). The worker uses an MCP client for `mcp` kind when not in simulation; the
  **simulation fallback is retained for the fake/native paths and logged at the boundary**.
- **(E) Side-effect skills in-sandbox.** `SandboxedExecutor` now routes **all** kinds (including
  `apply_repair` / `notify_parties` / `execute_return`) through the client → the worker, under the
  creation-time egress allowlist. Their **actual action stays the simulated implementation** (no real
  rail/notification in dev). `approve_actions`/SoD gating stays host-side and unchanged.
- **OTLP.** The worker returns an `otlp_trace_id` in `SandboxResult` → `actor_log`. In-sandbox it exports
  spans to `host.openshell.internal:4318/v1/traces`; in dev/CI export is a no-op (the id is still minted).

### Part D — OpenShell packaging (deploy layer, confirmed CLI)

Provisioning uses the **confirmed** CLI (ADR-019): `nemoclaw onboard` launches the worker inside a
sandbox (registers the inference provider, builds the image, creates the sandbox); `nemoclaw <sandbox>
mcp add` registers the sanctions MCP server into the in-sandbox registry; a creation-time **egress
allowlist** (`openshell policy set … policy.yaml`) permits RabbitMQ, `inference.local`, the MCP server,
and stub rails, with credential scoping. `docker-compose.yml` adds `capability-worker` as a **plain
service** under an opt-in `nemoclaw` profile (default compose stays `native`), plus commented
stub-inference / stub-mcp placeholders.

**`# [confirm]` (deploy layer) — RESOLVED in ADR-023:** the AMQP-egress question is **answered — allowed.**
Against the real `openshell` CLI (v0.0.80) + policy-schema docs, the sandbox egress policy supports a
**TCP-passthrough** endpoint (omit the `protocol` field), so **AMQP to RabbitMQ:5672 is a valid egress
rule** — `openshell policy update <sb> --add-endpoint 'host:5672:read-write'`. No AMQP-over-WebSocket or
HTTP-fallback is needed; the broker transport works in a real sandbox as-is. The worker image is placed via
`openshell sandbox create --from <image> --policy <yaml>`. (Also corrected: the CLI is `openshell`, not
`nemoclaw onboard`/`gateway start` — see ADR-023 for the real surface.) MCP is a first-class egress
protocol (`protocol=mcp`); OTLP live-verification is part of the pending end-to-end run (ADR-023 §Blockers).

## Consequences

- **The `nemoclaw` path is real, not fake-only.** With the worker enabled, capability execution happens
  in the (sandboxable) worker over the broker; `llm`/`mcp`/side-effect-skills all run there, host owns
  the audit trail. Fake remains the CI default; `native` byte-identical with flags off.
- **B/D/E delivered** inside the worker (LLM via `inference.local`, real MCP transport via the registry
  client with a stub list, side-effect skills sandboxed-but-simulated) — all unit-tested with no gateway;
  the real RabbitMQ round-trip is env-gated (`AGENTRT_OPENSHELL_IT`).
- **Seam preserved**: no change to the graph nodes, `CapabilityRunSpec`/`SandboxResult` shape (only
  additive fields: descriptor + constraints), memoization, or egress policy.
- **ADR-019's finding is resolved** (transport inverted); ADR-017 trap 6 updated; the dead HTTP client
  retired.
- **Supersedes** the ADR-017 stance that the descriptor stays out of the spec: the worker *is* the
  execution context, so the job carries the descriptor — which holds refs only, never secrets.

## Traps recorded for maintainers

1. **One execution core.** `skill`/`llm`/`mcp` dispatch lives only in `executor/core.py`. Don't fork it
   into the worker — both paths must call it or parity breaks.
2. **Host owns checkpoint + validate + memo + audit.** The worker returns raw outputs only. Never move
   the audit/checkpoint into the worker (ADR-017 trap 2).
3. **Secrets never cross the broker.** The job carries the model-config *ref* + a refs-only descriptor.
   Do not add resolved keys to `spec_to_job`; inference creds are OpenShell-brokered (ADR-018).
4. **Idempotency = memo + deterministic `request_id`.** The request id is derived from
   `(instance, element, inputs_hash, attempt)`; combined with the ADR-019 memo a resume/redelivery does
   not re-execute. Keep the attempt in the key (see ADR-019 trap 1).
5. **Retry only when idempotent.** `BrokerOpenShellClient` retries a timeout/worker-error solely for
   idempotent capabilities — mirroring the in-process policy. Don't retry side-effectful work.
6. **The worker is transport-plain.** It needs no OpenShell to run (dev/CI). OpenShell packaging is a
   deploy layer; the AMQP-egress / registry-shape / OTLP `# [confirm]`s live there, never guessed into
   the worker or broker code.
7. **`HttpOpenShellClient` stays retired.** OpenShell has no inbound execute API (ADR-019). Do not
   revive it; the real path is the broker + worker.
