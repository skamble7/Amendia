# ADR-022 — Portable Helm/Kubernetes deployment (base chart + per-provider overlays)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-016 (secret-refs / `literal:→vault:`), ADR-018 (ConfigForge refs, `inference.local/v1`),
  ADR-019/ADR-020 (capability-worker, broker transport, the **AMQP-egress `[confirm]`**, creation-time
  egress), ADR-021 (deep_agent), the design doc `amendia_secure_runtime_nemoclaw_plan.md` §11, and
  `backend/deploy/docker-compose.yml` (the dev substrate this translates).
- **Advances:** ships Amendia as a **portable base Helm chart + thin per-environment values overlays**
  (GKE first-class; EKS/AKS/on-prem scaffolded) — because Amendia ships per-bank onto GKE/EKS/AKS/on-prem.

## Context

Portability is the product: customers run different Kubernetes. So the deliverable is a **generic base
chart** with cloud-specific settings isolated to **values overlays behind marked seams** — never
hardcoded. Packaging is Helm + manual `helm` apply (no GitOps controller). The compose stack stays the
dev substrate; K8s is additive and does not touch `native`/dev.

## Decision

### Part A — Portable umbrella chart (`deploy/helm/amendia/`)

One umbrella chart renders every platform service (stub, ingestor, agent-runtime, process-registry,
identity, notification-service, config-forge, **capability-worker**, webui) from a `.Values.services`
map via a **generic Deployment/Service/ServiceAccount/PDB renderer** (`_helpers.tpl`), plus optional
in-cluster datastores (Mongo/RabbitMQ/Keycloak, `datastores.*.deploy`) so `helm template` renders a
self-contained stack offline — a bank disables these and points at managed/BYO endpoints. Standard
hardening in the base: resource requests/limits, liveness/readiness on `/health(z)`, PodDisruptionBudget,
non-root `securityContext` + dropped capabilities, per-service ServiceAccount. **Exit proof:** `helm lint`
+ `helm template` pass for all four overlays (62–64 resources each) — a live cluster is not required.
Install with release name **`amendia`** so in-cluster Service DNS matches the defaults.

### Part B — Vault-backed secrets via Kubernetes auth (portable)

Pods authenticate to Vault with their **K8s ServiceAccount** — identical on all four targets (no
per-cloud workload-identity dependency for secrets). Default method **CSI** (Secrets Store CSI + Vault
provider): a per-service `SecretProviderClass` syncs `secret/data/amendia/<svc>` into a per-service K8s
Secret consumed via `secretKeyRef`. **Agent Injector** is the documented values-toggle alternative
(`file:` refs). **No plaintext secret in Git/values/bare Secrets** (ADR-016 trap 1, verified: the
rendered manifests contain only `secretKeyRef`/`$(VAR)` refs). ConfigForge `ModelProfile` refs stay
`env:`/`file:`; the values they resolve to are Vault-sourced (provider keys, `OPENSHELL_INFERENCE_TOKEN`,
Keycloak/DB creds, `X-Amendia-Internal`). `deploy/vault/` ships the policy + role. This is the
`literal:→vault:` realization ADR-016 anticipated.

### Part C+F — Nemotron serving as one toggle + GPU scheduling

`inference.mode ∈ {nim-selfhosted, nvidia-hosted, bedrock-only}` (models are configuration — ADR-018):
- **`nim-selfhosted`** → renders the NIM workload onto the GPU node pool (nodeSelector/tolerations/
  `nvidia.com/gpu` limit, first-class in `values-gke`), and sets the active ConfigForge ref to the
  managed-proxy profile.
- **`nvidia-hosted`** → no cluster GPU; ref points at the hosted NVIDIA endpoint (egress allowed, Part E).
- **`bedrock-only`** → no NIM; ref stays Bedrock. `deep_agent` (ADR-021) needs a managed model, so it is
  available only where one is configured — documented.

Verified: the toggle renders the NIM workload **only** for `nim-selfhosted` and swaps the LLM ref per
mode. Implemented as values + a ConfigForge seed Job, not code (ADR-018). The NIM image/args/licensing
are `# [confirm]` against NVIDIA's NIM Helm packaging.

### Part D+E — capability-worker + egress NetworkPolicies

**Baseline (this phase):** the capability-worker is a **plain hardened Deployment** (replicas = the warm
pool) consuming the broker queues (ADR-020) — a fully valid production posture. Rendered only in
`nemoclaw` mode. **Egress NetworkPolicies:** namespace **default-deny egress** (+ DNS), then explicit
per-workload allowlists. The worker's allowlist — RabbitMQ, the inference endpoint (in-cluster NIM /
external), the MCP server, OTLP — is the **resolution of ADR-020's AMQP-egress `[confirm]`** on the
baseline path: a NetworkPolicy egress rule to RabbitMQ on TCP 5672. Allowlists are derived from the same
per-service `egress` tokens the contract-egress model uses (ADR-019), so policy tracks the pack.

### Part G — Observability (OTLP)

A minimal in-cluster OTLP collector (values-toggle) receives agent-runtime + worker traces
(`OTEL_EXPORTER_OTLP_ENDPOINT`); the `otlp_trace_id → actor_log` linkage (ADR-017/020) joins traces to
the Mongo audit trail by `process_instance_id` + `correlation_id`. The export backend is `# per-deployment`.

## Per-provider seam matrix (what each overlay sets)

| Seam | GKE (first-class) | EKS | AKS | on-prem |
|---|---|---|---|---|
| `global.storageClass` | `standard-rwo` | `gp3` | `managed-csi` | your CSI (local-path/Ceph/NFS) |
| GPU `nodeSelector` | `cloud.google.com/gke-accelerator` | `eks.amazonaws.com/nodegroup` | `agentpool` | `nvidia.com/gpu.present` |
| GPU tolerations | `nvidia.com/gpu` | `nvidia.com/gpu` | `nvidia.com/gpu` + pool taint | `nvidia.com/gpu` |
| `ingress.className` | `gce` | `alb` | `webapprouting…azure` | `nginx` |
| SA identity annotations | Workload Identity (opt) | IRSA `role-arn` (opt) | Workload Identity `client-id` (opt) | none |
| Datastores | managed or in-cluster | managed or in-cluster | managed or in-cluster | in-cluster (incl. Keycloak) |
| Secrets | Vault **K8s auth** (portable — same everywhere) | " | " | " |

GKE is fully wired; EKS/AKS/on-prem are **scaffolds** — every provider-specific value is marked
`# per-provider`; validate before prod.

## Consequences

- **One chart, four clouds.** Generic base; cloud specifics live only in overlays. `helm lint` +
  `helm template` green for GKE/EKS/AKS/on-prem is the exit proof (met).
- **Secrets are Vault-sourced, portable, plaintext-free.** K8s auth avoids per-cloud identity coupling.
- **Nemotron is a one-line toggle.** Self-hosted NIM on GPU, NVIDIA-hosted, or Bedrock-only.
- **dev/`native` untouched.** Compose remains the dev substrate; prod runs `nemoclaw` fail-closed.

## `[confirm]` / deferred (do not invent)

1. **NemoClaw K8s sandbox mechanism** (operator/CRD/DaemonSet) is **unconfirmed** — so the worker runs as
   a plain hardened Deployment + NetworkPolicy (a valid posture). The OpenShell-sandbox enhancement is
   **gated** behind `openshell.sandbox.enabled` (default off) and **STOP**: not implemented until
   confirmed. Baseline is unaffected.
2. **AMQP egress via the OpenShell egress proxy** (HTTP-method/path-level per ADR-019/020): resolved for
   the **baseline** as a NetworkPolicy rule to RabbitMQ:5672. Whether the *sandbox* proxy allows an
   AMQP/TCP allowlist (vs HTTP-only, needing AMQP-over-WebSocket) stays `# [confirm]` for the sandbox path.
3. **NVIDIA NIM Helm packaging** (image/args/licensing `NGC_API_KEY`) — the in-chart NIM workload is a
   `# [confirm]` placeholder; swap for NVIDIA's official NIM subchart once confirmed.
4. **CNI egress portability** (Calico/Cilium/GKE-native) — extra `ipBlock`s may be needed `# per-provider`.
5. External-target egress (nvidia-hosted inference, Bedrock, MCP) uses a broad `0.0.0.0/0:443` rule —
   `# per-provider`: tighten to the endpoint's CIDRs.

## Traps recorded for maintainers

1. **Portable by construction.** Cloud specifics live only in overlays behind `# per-provider` seams;
   never hardcode a cloud in the base chart or templates.
2. **No secret in Git/values/plaintext Secrets.** Vault-sourced; ConfigForge refs stay refs. If you add
   a secret env, add it to the service's `secretEnv` + the Vault path — never inline a value.
3. **Don't invent NemoClaw/NIM K8s APIs.** Baseline = plain worker Deployment + NetworkPolicy. Sandbox/NIM
   specifics unconfirmed → `# [confirm]` + STOP; never guess a CRD/operator/subchart.
4. **Release name matters.** Cross-service DNS defaults assume release `amendia`; install/template with
   that name or override the URL values.
5. **Prod is fail-closed.** `executionMode=nemoclaw` + `nemoclawRequired=true`; the worker only renders in
   nemoclaw mode.
