# Amendia — Operator Runbook: running & testing in `native` vs `nemoclaw` mode

**Audience:** platform / ops engineers running Amendia.
**Scope:** how to run and test a process pack in either execution mode — locally on Apple Silicon, in dev
(compose), and in prod (Helm/K8s).
**Intended location:** `backend/docs/amendia_nemoclaw_operator_runbook.md`.
**Backing decisions:** ADR-017 (execution mode), ADR-018 (nemoclaw inference provider), ADR-019
(memoization + egress policy), ADR-020 (in-sandbox broker worker), ADR-021 (`deep_agent`), ADR-022
(portable Helm/K8s), **ADR-023 (real OpenShell bring-up — confirmed CLI surface + the AMQP verdict)**.

> **Synced to ADR-023.** The real CLI is **`openshell` (v0.0.80)** — earlier docs guessed
> `nemoclaw onboard` / `gateway start`; those are superseded. **AMQP egress is confirmed allowed**
> (TCP passthrough). The command surface below is the confirmed one.

---

## 1. The two modes at a glance

| | **`native`** (default) | **`nemoclaw`** |
|---|---|---|
| Where capabilities run | in-process, on the agent-runtime host | in a **capability-worker** (sandboxable), reached over RabbitMQ request/reply |
| Set by | `AGENTRT_EXECUTION_MODE=native` | `AGENTRT_EXECUTION_MODE=nemoclaw` |
| LLM | polyllm/ConfigForge (Bedrock/OpenAI/Gemini) | same, or Nemotron via `inference.local/v1` (gateway-brokered) |
| MCP (sanctions) | simulation | real transport (`list_provider` stub in dev) |
| Side-effect skills | simulated, in-process | simulated, but jailed in the sandbox under an egress allowlist |
| `deep_agent` capabilities | **refused** (fail closed) | supported (HITL-gated, memoized) |
| Extra guarantees | — | credential isolation, egress allowlists, OTLP traces |

**Orthogonal switches** (they compose — don't conflate):
`AGENTRT_EXECUTION_MODE` = *where* it runs · `AGENTRT_SIMULATION_MODE` = *whether* it's real vs sim ·
`AGENTRT_LLM_CONFIG_REF` / `runtime.model_config_key` = *which* model. `native` is byte-for-byte the
pre-NemoClaw behaviour.

---

## 2. Testing on your local Apple Silicon Mac (`nemoclaw` mode)

There are **two levels**. Start with Level 1 — it needs no OpenShell, no GPU, no credential, and
exercises the entire nemoclaw code path (worker, broker, memoization, egress policy, `deep_agent`).

### Level 1 — compose `nemoclaw` profile (works today, zero external deps)

The worker runs as a plain process; inference and MCP are stubbed. This is the fast, offline test.

1. **Branch:** `git checkout feat/adopt-nemoclaw` (until merged).
2. **Bring up the stack + nemoclaw profile** (adds `capability-worker` + stub inference + stub MCP):
   ```bash
   docker compose -f backend/deploy/docker-compose.yml --profile nemoclaw up -d
   ```
3. **Point agent-runtime at nemoclaw** (env on the agent-runtime service):
   ```
   AGENTRT_EXECUTION_MODE=nemoclaw
   AGENTRT_CAPABILITY_WORKER_ENABLED=true
   AGENTRT_SIMULATION_MODE=true          # fully offline; set false for real (stubbed) inference
   AGENTRT_NEMOCLAW_REQUIRED=false       # dev; use true in prod (fail closed)
   AGENTRT_LLM_CONFIG_REF=dev.llm.nemoclaw.nim
   # AGENTRT_WORKER_INFERENCE_BASE_URL is preset by the profile to the stub endpoint
   ```
4. **Onboard the seed packs** (the registry `onboard_seed` path): `wire-repair-standard` (runs in either
   mode) and `wire-repair-agentic@1.0.0` (the `deep_agent` pilot — nemoclaw-only).
5. **Drive an exception:** `tools/demo_wire_repair.sh`, or `POST :8081/exceptions/generate`.
6. **Verify (what "it worked in nemoclaw" looks like):**
   - `GET :8083/instances/{id}` → capability entries in `actor_log` carry `exec_meta.otlp_trace_id`
     (native never sets this — proof it went through the worker).
   - The `capability-worker` logs show it **consuming** `capability_exec_request` jobs and replying.
   - Approve a `review_after` gate → the capability is **not** re-invoked on resume (memoization).
   - The agentic pack runs its `deep_agent` step via the deterministic `FakeDeepAgentRunner`.

**Bonus — the real RabbitMQ round-trip, still no OpenShell:** the broker integration tests are env-gated;
run them with `AGENTRT_OPENSHELL_IT=1 pytest …` to exercise `RabbitBrokerTransport` over the real broker.

### Level 2 — a real OpenShell sandbox (confirmed `openshell` CLI, more involved)

Runs the worker **inside** a real OpenShell sandbox. Needs Docker Desktop + the `openshell` CLI, and — for
the gateway — either NVIDIA's `install.sh` (a **launchd service**, a system change) or the prebuilt
binaries run directly. Real `llm` inference additionally needs an operator credential.

**Honest caveats first:** OpenShell is **alpha (v0.0.80, fast-moving)**; the gateway install adds a
persistent **launchd service on :17670** (reversible); and in a **nested Docker-Desktop** setup the egress
proxy may not complete data-plane byte flow to *any* upstream (ADR-023 saw the *allowed* Anthropic
endpoint fail identically to RabbitMQ) — so run the byte-flow check on a **non-nested** setup. The
**policy/architecture verdict (AMQP allowed) is already confirmed**; Level 2 is behavioral confirmation.

1. **Install the client + preflight:**
   ```bash
   uv tool install openshell        # client only; does NOT start the gateway
   openshell doctor check           # validates Docker prerequisites
   ```
2. **Gateway** — either NVIDIA's installer (adds the launchd service):
   ```bash
   curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
   ```
   …or run the prebuilt gateway directly (no launchd), per ADR-023: `openshell-gateway generate-certs …`
   then `openshell-gateway --port 17670 …`. Then register + check:
   ```bash
   openshell gateway add https://127.0.0.1:17670 --local --name openshell --gateway-insecure
   openshell status
   ```
3. **Build the worker image** (the same `capability-worker` the compose profile runs): `docker build … -t
   amendia/capability-worker:dev`.
4. **Author `worker-policy.yaml`** with the AMQP **TCP-passthrough** endpoint (the confirmed ADR-023
   shape — note **no `protocol:` field**):
   ```yaml
   network_policies:
     amendia-rabbitmq-amqp:
       endpoints:
       - host: host.docker.internal   # your RabbitMQ host as seen from the sandbox
         port: 5672
         access: read-write           # NO protocol: ⇒ TCP passthrough (raw AMQP)
   # add similar endpoints for inference.local, the MCP server (protocol: mcp), and OTLP as needed
   ```
5. **Create the sandbox from the worker image:**
   ```bash
   openshell sandbox create --name amendia-worker --from amendia/capability-worker:dev --policy worker-policy.yaml
   openshell sandbox logs amendia-worker      # confirm it connects to RabbitMQ and consumes jobs
   ```
6. **(Real `llm` only)** register the inference provider so creds are injected gateway-side (the sandbox
   holds only a placeholder): `openshell inference set <provider> <model>` + `openshell provider …`.
7. **Point agent-runtime at nemoclaw** (as Level 1, with `SIMULATION_MODE=false` for real inference) and
   **drive an AC01 exception**; verify `actor_log` trace ids as in §6.
8. **Teardown:** `openshell sandbox delete amendia-worker`; `openshell gateway destroy` (if installed);
   `uv tool uninstall openshell`.

> **The one residual to close (ADR-023):** actual AMQP **bytes** through the passthrough were not observed
> (nested-Docker egress limit). On a non-nested Mac, `openshell sandbox exec amendia-worker` a short AMQP
> connect-and-consume against RabbitMQ and watch it survive a heartbeat interval + a forced broker blip —
> that closes the last behavioral check. Low risk (raw TCP relay + aio-pika robust reconnect).

---

## 3. Running in dev (`native`)

`docker compose up` (default profile). Onboard a pack (§5), drive an exception (§6). This is the existing
local-dev experience; nothing about it changed.

---

## 4. Running in prod (Helm / Kubernetes)

Chart: `deploy/helm/amendia/` with overlays `values-{gke,eks,aks,onprem}.yaml` (GKE fully wired; others
scaffolded, seams marked `# per-provider`). Manual `helm`.

1. **Vault** (K8s auth, portable): apply the policy/role from `deploy/vault/`; provider keys,
   `OPENSHELL_INFERENCE_TOKEN`, Keycloak/DB creds, `X-Amendia-Internal` are Vault-sourced — never in values.
2. **Inference mode:** `inference.mode = nim-selfhosted | nvidia-hosted | bedrock-only` (one value picks the
   ConfigForge ref + conditionally renders NIM on GPU nodes).
3. **Render:** `helm lint deploy/helm/amendia -f …/values-gke.yaml` then `helm template …` (green is the exit
   bar). **Install:** `helm install amendia deploy/helm/amendia -f values-<env>.yaml -n <ns>`.
4. **Mode:** prod nemoclaw runs `executionMode=nemoclaw` + `nemoclawRequired=true` (fail closed). Egress is
   **default-deny + allowlists**; the worker's RabbitMQ:5672 rule is the baseline AMQP resolution.
5. **OpenShell on K8s (optional, gated):** OpenShell ships a **Kubernetes driver** (`sandbox create
   --driver-config-json '{"kubernetes":{"pod":{"node_selector":…}}}'`, confirmed in ADR-023) — the baseline
   is a plain hardened worker Deployment; the sandbox path is `openshell.sandbox.enabled` pending cluster
   validation.

---

## 5. Onboarding a process pack (same in every mode)

Mode changes *how* capabilities execute, not *how* packs are authored: register artifact schemas → register
capabilities → `POST /packs` → `PUT …/bpmn` → `POST …/validate` → `POST …/activate`. `wire-repair-standard`
runs in either mode; **`wire-repair-agentic@1.0.0`** binds the `deep_agent` capability under a `review_after`
gate and **only runs in `nemoclaw` mode** (§7).

---

## 6. Verifying a nemoclaw run

- **Went through the sandbox/worker:** `actor_log` entries carry `exec_meta.otlp_trace_id` (native never sets it).
- **Memoization:** a `review_after` approve does **not** re-invoke the capability on resume.
- **Real MCP transport:** the sanctions step runs through the MCP client (`list_provider` stub); the
  sim-fallback boundary is logged when the server is unreachable.
- **Inference:** the log shows the ConfigForge resolve + the provider/model that produced each artifact.

---

## 7. `deep_agent` — the one thing that trips people

The agentic pack **fails closed** unless all hold: **`nemoclaw` mode** (refused in native — no runner);
**HITL-gated**; **memoized** (mandatory regardless of `MEMOIZE_CAPABILITIES`; needs a memo store);
**`read_only`** by default; and **a managed model** (not `bedrock-only` unless a Bedrock managed ref is
set). If the agentic pack "won't run," you're almost certainly not in `nemoclaw` mode with the worker up.

---

## 8. Configuration quick reference (agent-runtime, `AGENTRT_` prefix)

| Setting | Purpose | Default |
|---|---|---|
| `EXECUTION_MODE` | `native` \| `nemoclaw` | `native` |
| `CAPABILITY_WORKER_ENABLED` | use the broker worker (else the fake) in nemoclaw mode | `false` |
| `NEMOCLAW_REQUIRED` | fail closed if the worker/gateway path is unavailable | `false` |
| `SIMULATION_MODE` | deterministic sim (orthogonal to mode; keep `true` in CI) | per env |
| `LLM_CONFIG_REF` | platform-wide model ref | `dev.llm.bedrock.explicit-creds` |
| `WORKER_INFERENCE_BASE_URL` | worker's inference endpoint (stub locally; `inference.local/v1` in a sandbox) | stub in profile |
| `MCP_REGISTRY_PATH` | in-sandbox MCP registry file | per env |
| `MEMOIZE_CAPABILITIES` | opt-in memo for deterministic kinds (mandatory anyway for `deep_agent`) | `false` |
| `OPENSHELL_TOKEN` | gateway/broker auth (ref → Vault in prod) | — |
| `SANDBOX_POOL_SIZE` | warm-pool concept (≈ worker replicas in K8s) | `4` |
| `MEMO_COLLECTION` | Mongo collection for the memo store | `capability_memo` |
| `OPENSHELL_IT` | enable env-gated broker integration tests | off |

**ConfigForge LLM refs:** `dev.llm.bedrock.explicit-creds` (default), `dev.llm.nemoclaw.nim` (directly
reachable NIM), `dev.llm.nemoclaw.nemotron-ultra` (in-sandbox managed proxy), + OpenAI/Gemini. Change models
with a `PUT` on the ConfigForge entry — no redeploy (ADR-018). Descriptor edits require re-onboarding
(ADR-016 trap 3).

**Real `openshell` CLI surface (v0.0.80):** top-level `sandbox · service · forward · logs · policy ·
settings · provider · gateway · status · inference · doctor · term`. Key: `sandbox
create|get|list|delete|exec|connect|upload|download`; `policy set|update|get|list|prove`; `gateway
add|remove|login|select|info|list`; `inference set|update|get`. `--add-endpoint 'host:port:read-write'`
with **no protocol** = TCP passthrough (AMQP).

**Service ports:** stub 8081, ingestor 8082, agent-runtime 8083, registry 8084, identity 8086, keycloak
8087, notification 8088, config-forge 8040; OpenShell gateway 17670.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| agent-runtime won't start in nemoclaw | `NEMOCLAW_REQUIRED=true` + worker/broker unreachable (fail-closed) | bring the worker up / fix the broker; or `false` in dev |
| agentic pack "refused" / won't run | native mode, no HITL gate, or no memo store | run `nemoclaw` with the worker + memo store; gate the binding (§7) |
| no `otlp_trace_id` in `actor_log` | actually in `native`, or worker not enabled | set `EXECUTION_MODE=nemoclaw` + `CAPABILITY_WORKER_ENABLED=true` |
| approved gate re-ran the model | memoization off for a deterministic kind | `MEMOIZE_CAPABILITIES=true` (already forced for `deep_agent`) |
| "using simulation fallback" for MCP | MCP server unreachable / fake path | expected in dev; wire the MCP server for real transport |
| sandbox egress to RabbitMQ blocked | missing/incorrect policy endpoint | `openshell policy update <sb> --add-endpoint 'host:5672:read-write'` (no protocol) |
| sandbox reaches nothing (all egress fails) | nested Docker-Desktop proxy limit (ADR-023) | run on a non-nested Mac; not an AMQP/policy problem |
| model change didn't take | polyllm caches the client per ref per process | restart agent-runtime/worker |

---

## 10. Open items (status after ADR-023)

- **AMQP sandbox egress** — **RESOLVED: allowed** (TCP passthrough; policy shown §2/§8). No HTTP fallback needed.
- **Data-plane byte flow** — the one residual: AMQP *bytes* through the passthrough not yet observed
  (nested-Docker limit); close it on a non-nested Mac (§2 Level 2 note). Low risk.
- **Live inference (real `llm` in a sandbox)** — needs an operator credential; mechanism confirmed
  (`inference set`/`provider`, gateway-brokered).
- **Gateway system install** — `install.sh` adds a launchd service; a knowing choice (or run the prebuilt
  binaries directly).
- **OpenShell on K8s** — driver **confirmed to exist** (ADR-023); full cluster wiring still to validate.
- **NIM Helm packaging** (`NGC_API_KEY`, image/args) — `# [confirm]` against NVIDIA's NIM subchart.
- **OTLP live verification** — pending the first real end-to-end sandbox run.
- **Alpha caveat** — OpenShell v0.0.80, fast-moving; pin the version and re-run `openshell doctor check`.

---

## 11. ADR / doc map

- **ADR-017** — `native`/`nemoclaw` execution mode + the executor seam.
- **ADR-018** — polyllm `nemoclaw` provider + ConfigForge Nemotron refs.
- **ADR-019** — memoization (fixes the `review_after` replay trap) + contract-derived egress policy.
- **ADR-020** — in-sandbox capability-worker over the RabbitMQ broker (the transport pivot).
- **ADR-021** — the `deep_agent` capability kind.
- **ADR-022** — portable Helm/K8s deployment (Vault, inference toggle, egress NetworkPolicy).
- **ADR-023** — real OpenShell bring-up: confirmed `openshell` CLI surface + the AMQP-egress verdict.
- **`amendia_secure_runtime_nemoclaw_plan.md`** — design/rationale (two planes of autonomy, phasing).
- **`amendia_llm_configuration_guide.md`** — configuring/rotating models.
- **`amendia_agent_runtime_execution_pipeline.md`** — the execution engine reference.
