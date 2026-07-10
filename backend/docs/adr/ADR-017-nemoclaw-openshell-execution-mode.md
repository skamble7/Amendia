# ADR-017 — NemoClaw / OpenShell as a configurable execution mode (Phase 1)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-009/ADR-011 (agent-runtime foundation + execution — the pure/sync nodes, the async
  engine, and the **executor seam** this extends), ADR-016 (real LLM via polyllm + ConfigForge — the
  `_run_blocking` bridge, the secret-refs model, and the traps this builds on), the design doc
  `amendia_secure_runtime_nemoclaw_plan.md` (v2), and `amendia_agent_runtime_execution_pipeline.md`.
- **Advances:** makes NemoClaw's **OpenShell** secure sandbox a **selectable execution substrate** for
  capability execution, without changing the orchestration plane, the contracts, or `native`-mode
  behaviour.

## Context

ADR-011 concentrated **all** capability dispatch behind one seam — a graph node gathers inputs, calls an
*injected executor*, validates the outputs against the pinned artifact schema, and returns a state delta;
**all** I/O (Mongo checkpointing, Rabbit, registry) lives in the async engine *around* the pure/sync
node. Every dangerous thing — arbitrary `skill` code, real `llm` calls, `mcp` tool calls, and the
money-moving side-effect skills — passes through that seam; everything trusted (the checkpointer = the
audit trail, the HITL decision API) is already on the other side.

NVIDIA + LangChain's **NemoClaw Deep Agents Blueprint** (announced 2026-07-08) ships **OpenShell**: a
governed, containerized sandbox with network-egress allowlisting, credential isolation (real secrets stay
host-side; the sandbox sees only scoped placeholders), a managed inference proxy, OTLP tracing, and native
MCP brokering. The executor seam is exactly the minimal cut that already fronts the whole external-call
surface — so adopting OpenShell is an *executor swap*, not a rewrite. Jailing the whole `:8083` service
would instead drag the checkpointer inside the boundary and widen the credential surface.

This ADR implements **Phase 1 of the design doc §10**: the mode flag + a `SandboxedExecutor` covering the
`llm` and `mcp` kinds, delivered buildable and fully testable **without** a live gateway. Later phases
(Nemotron provider, side-effect-skill sandboxing, the `deep_agent` capability, the real HTTP client,
K8s/Helm) are explicitly deferred.

## Decision

### Part A — execution mode config (`app/config.py`, `AGENTRT_` prefix)

New settings, orthogonal to `SIMULATION_MODE` (whether execution is real) and
`LLM_CONFIG_REF`/`model_config_key` (which model):

- `EXECUTION_MODE: Literal["native","nemoclaw"] = "native"` — the master switch (**where** a capability
  runs).
- `OPENSHELL_URL: str | None = None` — gateway endpoint; unset ⇒ the deterministic fake client.
- `NEMOCLAW_REQUIRED: bool = False` — fail-closed posture (see Part E).
- `SANDBOX_POOL_SIZE: int = 4` — warm-pool size for the real client (a Phase-1 scaffold).

`native` is the default everywhere (config, compose, CI). The three switches **compose**: CI stays on
`native` + `SIMULATION_MODE=true`, unaffected.

### Part B — `Executor` protocol + `InProcessExecutor`

Today's `dispatch.py` executor class was renamed `InProcessExecutor` (pure rename — zero behaviour
change) and a `runtime_checkable` **`Executor` Protocol** (`execute(descriptor, inputs, ctx) -> outputs`,
the unchanged signature) was defined in `executor/base.py`. Both executors return the same shape and may
add an optional `"exec_meta"` dict. The real-LLM primitive was extracted from `_execute_llm_real` into a
module-level `run_real_llm(...)` so the OpenShell fake reuses the *exact same* polyllm call rather than
duplicating it.

### Part C — OpenShell client abstraction (`executor/openshell/client.py`)

All sandbox I/O sits behind a small interface so Phase 1 is testable now and the live gateway drops in
later:

- `OpenShellClient` **Protocol** — `async run_capability(spec) -> SandboxResult` and `async ping() -> bool`.
- `CapabilityRunSpec` — carries what a sandbox needs and *nothing it shouldn't*: capability id/kind,
  pinned input artifacts, the declared **output JSON schema(s)**, the selected model-config **ref** (not
  the key value), an egress-policy handle (placeholder in Phase 1), the element id, and the sim flag.
- `SandboxResult` — `outputs` (artifact_key → data, consumed by the host's existing `_validate`),
  `otlp_trace_id`, and provider/model for the `actor_log` line.
- `FakeOpenShellClient` — **deterministic, no network.** Executes the same capability logic the
  in-process path would (simulation skills, or `run_real_llm`), returning schema-valid artifacts and a
  synthetic `fake-otlp-<element>-<n>` trace. Auto-selected when `OPENSHELL_URL` is unset — the CI/dev
  substrate that proves the seam end-to-end.
- `HttpOpenShellClient` — a **scaffold** for the live gateway; every wire detail is marked
  `# [confirm] against live NemoClaw docs` and `run_capability` raises until confirmed. Not exercised in
  Phase 1.

### Part D — `SandboxedExecutor` (`executor/sandboxed.py`)

Implements `Executor`. For `llm`/`mcp` kinds it builds a `CapabilityRunSpec`, calls the client through
the ADR-016 `_run_blocking` bridge, and returns `{"outputs", "log", "exec_meta"}` — handing `outputs` to
the caller's **existing** `_validate` (no duplicated validation). For `skill` kinds it **delegates to
`InProcessExecutor`** and logs that they ran un-sandboxed (side-effect-skill sandboxing is Phase 3). The
`otlp_trace_id` + provider/model are threaded into the element's `actor_log` entry; the log line follows
ADR-016's style with `via OpenShell sandbox trace=<id>` appended. A per-instance **memoization hook**
(keyed on `(element, inputs-hash)`) is wired as a seam and left a no-op — `# Phase 3/4`.

The trace metadata reaches the audit trail via an **additive, native-safe** change to the task runner:
`_produce_outputs` now returns `(committed, exec_meta)` and `actor_entry(..., meta=...)` attaches an
`exec_meta` key **only when present**. In `native` mode `exec_meta` is always `None`, so `actor_log`
entries are byte-for-byte unchanged. The gather → execute → validate → commit → log pipeline is unchanged
in shape.

### Part E — executor selection + fail-closed (`executor/factory.py`, wiring)

`build_executor(settings)` runs at engine-wiring time (in `main.py`'s lifespan): `native` →
`InProcessExecutor`; `nemoclaw` → probe the gateway once via `ping()`, then `SandboxedExecutor` if
reachable. If unreachable: `NEMOCLAW_REQUIRED=true` raises `NemoClawUnavailable` (lifespan aborts —
**fail closed**, the right default for a payments platform); `false` degrades to `native` with a loud
warning (dev only). The fake always reports reachable, so `nemoclaw` mode runs in dev/CI with no gateway.

### Part F — LLM path (thread-only) + deploy scaffolding

Model selection is unchanged (polyllm/ConfigForge, `LLM_CONFIG_REF` / `descriptor.runtime.model_config_key`).
Phase 1 only ensures the selected **ref** flows into `CapabilityRunSpec` so the real client can later
route it through the managed inference proxy — `# [confirm] managed inference proxy — Phase 2`. The
`providers/nemoclaw.py` polyllm adapter is **not** built here. `docker-compose.yml` gains commented
`AGENTRT_EXECUTION_MODE` env and an `openshell-gateway` service scaffold (marked `# [confirm]`); default
compose behaviour stays on `native`.

## Consequences

- **NemoClaw is a config flag, not a rewrite.** With `AGENTRT_EXECUTION_MODE=native` (default) every
  existing code path, test, and demo is byte-for-byte unchanged (the full pre-existing suite passes with
  only the `Executor → InProcessExecutor` rename). Flipping to `nemoclaw` swaps only the injected
  executor.
- **Exit proof (design §10, Phase 1).** With the fake client, a driven AC01 exception runs to
  `outcome=End_Resolved` with `Task_DraftRepair` (`llm`) and `Task_SanctionsRescreen` (`mcp`) executing
  **through the `SandboxedExecutor`**, schema validation intact, and the `actor_log` capability entries
  carrying `exec_meta.otlp_trace_id`. A native-vs-nemoclaw(fake) invariance test asserts identical
  committed artifacts and identical `actor_log` structure (modulo the added trace id) — the seam is
  transparent.
- **The credential-surface win is scaffolded, not yet realized.** Only the model-config *ref* crosses the
  spec boundary; real secrets never do. Actually moving provider keys into the gateway lands with the
  real client + managed inference proxy (Phase 2/5).
- **Deliberately deferred:**
  - **Phase 2** — the polyllm `nemoclaw` provider (`providers/nemoclaw.py`) + Nemotron ConfigForge refs.
  - **Phase 3** — side-effect-skill sandboxing (egress allowlists + brokered creds), real sanctions MCP,
    and per-instance artifact **memoization** (fixes ADR-016 trap 2 for sandboxed replays).
  - **Phase 4** — the `deep_agent` capability kind (Deep Agents harness inside the sandbox) + registry
    validation.
  - **Phase 5** — K8s/Helm, Nemotron NIM on GPU, NetworkPolicy egress, Vault-backed gateway secrets.
  - The real **`HttpOpenShellClient`** wiring is a guarded scaffold only.
- **Open questions (`[confirm]` against live NemoClaw docs):** gateway execute endpoint + request/response
  shape; health path; sandbox lifecycle + warm-pool/snapshot semantics; per-sandbox egress policy +
  credential-scoping expression; managed inference proxy API shape (OpenAI-compatible?); native-MCP
  wiring from `mcp.server_key`; official compose fragment / Helm charts / GPU requirements.

## Traps recorded for maintainers

1. **`native` is the invariant.** Any change under `executor/` must keep `EXECUTION_MODE=native`
   byte-for-byte. The `actor_log` trace metadata is additive: `exec_meta` appears **only** when an
   executor returns it, which `InProcessExecutor` never does. Do not make `exec_meta` unconditional.
2. **Host checkpoints; sandbox returns data.** The sandbox only returns artifact JSON; the host still
   owns every Mongo write and checkpoint (the audit record). Never move the audit write off-host into a
   client.
3. **Secrets never enter the sandbox as raw values.** `CapabilityRunSpec` carries a model-config *ref*
   (e.g. `dev.llm.bedrock.explicit-creds`), never a key. Keep it that way when the real client lands —
   resolve secrets in the gateway, not by stuffing them into the spec or the sandbox env (a careless env
   passthrough silently undoes the ADR-016 trap-1 win).
4. **Sync node → async client** relies on the engine running nodes in a worker thread; the sandbox call
   reuses ADR-016's `_run_blocking`, which must keep handling both no-loop and running-loop cases.
5. **`review_after` re-runs on resume** (ADR-016 trap 2) — and a sandbox round-trip sharpens the cost.
   The memoization seam in `SandboxedExecutor` is the planned fix (Phase 3) and becomes **mandatory** for
   non-deterministic `deep_agent` capabilities (Phase 4). It is a no-op today.
6. **`HttpOpenShellClient` is unverified.** Every wire detail is a `[confirm]` placeholder and
   `run_capability` raises. Do not point `OPENSHELL_URL` at a real gateway until the format is confirmed
   against live docs; leave it unset to use the fake.
7. **Orchestration stays deterministic.** OpenShell is an *execution* substrate for a single node; the
   BPMN → compiled LangGraph plan is never handed to an agent. Keep autonomy off the orchestration plane.
