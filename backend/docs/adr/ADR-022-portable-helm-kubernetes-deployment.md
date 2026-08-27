# ADR-022 — Portable Helm/Kubernetes deployment (base chart + per-provider overlays)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-016 (secret-refs / `literal:→vault:`), ADR-018 (ConfigForge refs, `inference.local/v1`),
  ADR-019/ADR-020 (capability-worker, broker transport, the **AMQP-egress `[confirm]`**, creation-time
  egress), ADR-021 (deep_agent), the design doc `amendia_secure_runtime_nemoclaw_plan.md` §11, and
  `backend/deploy/docker-compose.yml` (the dev substrate this translates).
- **Advances:** ships Amendia as a **portable base Helm chart + thin per-environment values overlays**
  (GKE first-class; EKS/AKS/on-prem scaffolded) — because Amendia ships per-bank onto GKE/EKS/AKS/on-prem.

> **Revision (2026-08-19, chart 0.2.0):** the decisions below stand, but the chart as shipped had drifted
> from several of them and never covered ADR-058 onward. Parts A, B, E and G are amended — see
> **§ Revision — 2026-08-19** at the end of this ADR before relying on the Decision text.

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

> **Update (ADR-023):** items 1 and 2 are now substantially resolved against the real `openshell` CLI
> (v0.0.80). OpenShell ships a **Kubernetes driver** (`sandbox create --driver-config-json
> '{"kubernetes":{"pod":{"node_selector":…}}}'`) — the K8s sandbox mechanism exists (not operator-invented);
> full cluster wiring still to validate. And **AMQP sandbox egress is allowed** (TCP passthrough — omit the
> policy `protocol` field), so the sandbox path is not blocked. See ADR-023.

1. **NemoClaw/OpenShell K8s sandbox mechanism** — **partially resolved (ADR-023):** OpenShell has a
   Kubernetes driver. The baseline (plain hardened Deployment + NetworkPolicy) remains valid and default;
   the OpenShell-sandbox enhancement stays gated (`openshell.sandbox.enabled`) pending cluster validation.
2. **AMQP egress via the OpenShell egress proxy** — **RESOLVED (ADR-023): allowed** on the sandbox path via
   a TCP-passthrough policy endpoint (in addition to the baseline NetworkPolicy rule to RabbitMQ:5672).
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
6. **A values seam that no template reads is a lie.** `global.storageClass` and `datastores.*.storage` sat in
   the base values *and all four overlays* for six weeks while `datastores.yaml` rendered no volumes at all —
   the chart advertised persistence it did not have. When you add a seam, add the template that consumes it in
   the same change, and assert it in the render check.
7. **A PVC-backed Deployment must not roll.** Single-replica datastore Deployments mount `ReadWriteOnce`
   volumes; with the default `RollingUpdate` strategy `maxSurge` resolves to 1 and `maxUnavailable` to 0, so
   the replacement pod is scheduled before the old one releases the volume and blocks on a single-attach CSI
   driver. Use `strategy: { type: Recreate }` (or a StatefulSet). **Open as of chart 0.2.0** — see the Revision.

## Revision — 2026-08-19 · chart 0.2.0

Chart 0.1.0 was never revised after this ADR was accepted (2026-07-10), so it predated **ADR-058** (GLEA on
OTel + ClickHouse) and everything after it. Five defects plus one egress bug were found while bringing
`backend/docs/devops/Amendia_Component_Inventory_DevOps.xlsx` current, and closed by CC via
`_build-prompts/claude_code_prompt_helm_prod_chart_catchup.md` (report:
`_build-reports/claude_code_prompt_helm_prod_chart_catchup_report.md`). **Chart, values, `deploy/vault/` and
chart docs only — no application code, no compose change.** Reviewed against the diff 2026-08-19.

### What was wrong

1. **The audit system-of-record had no production packaging.** `glea-service` was absent from Part A's
   `.Values.services` map and no ClickHouse datastore existed — so `audit_events`, `cohort_events` and
   `cohort_sla_events` (ADR-058/063/064) were dev-compose-only.
2. **No persistence anywhere.** No template referenced `PersistentVolumeClaim`, `volumeClaim` or
   `storageClass`; `datastores.yaml` rendered bare Deployments with no volumes. An in-cluster Mongo or
   RabbitMQ lost everything on restart or reschedule, while the values — and the per-provider seam matrix
   above — implied otherwise. See trap 6.
3. **Part G threw traces away.** The collector ConfigMap exported the traces pipeline to `debug` (stdout), and
   `otel.collectorImage` pinned the **non-contrib** image, which has no ClickHouse exporter.
4. **The shipped Vault default contradicted Part B.** Part B specifies CSI as the default, but `values.yaml`
   shipped `method: agent-injector`, and `secretproviderclass.yaml` renders only under `csi` — so a default
   install produced **zero** SecretProviderClasses.
5. **`webui`'s Part E allowlist was incomplete.** `webui/nginx.conf` proxies `/api/identity/` and `/api/glea/`,
   but neither target was in its `egress` list — both blocked under default-deny.

### What changed

- **Part A** — service list is now stub-trigger-generator, ingestor, agent-runtime, process-registry, identity,
  notification-service, config-forge, **glea-service**, capability-worker, webui. Datastores gain
  **clickhouse** (8123 HTTP + 9000 native). Both were added as **pure values entries**: the generic
  Deployment/Service/ServiceAccount/PDB/SecretProviderClass/NetworkPolicy renderers picked them up with no new
  template, which is the portability property Part A claims, exercised for the first time. Exit proof moves
  from 62–64 to **74 rendered resources**; `helm lint` + `helm template` green on defaults + all four overlays.
- **Part A (persistence)** — a datastore with `deploy: true` and a `storage` value now renders a PVC (RWO,
  `storageClassName` from `global.storageClass`, **omitted entirely when `""`** so the cluster default applies)
  mounted at its data path: mongodb 10Gi `/data/db`, rabbitmq **8Gi** `/var/lib/rabbitmq` (new — the Helm
  counterpart of the missing compose volume; the durable GLEA audit queue now survives a restart), clickhouse
  50Gi `/var/lib/clickhouse`. No `storage` or `deploy: false` ⇒ ephemeral, unchanged. The hardcoded port switch
  became a name→port(s) map supporting multi-port datastores.
- **Part B** — `vault.method` default is now genuinely `csi`, matching what Part B always said.
  `secret/data/amendia/glea-service` added to `policy.hcl`; the glea ServiceAccount added to the role binding
  in `deploy/vault/README.md`.
- **Part E** — `$ports` gained `glea-service: 8090` and `clickhouse: [8123, 9000]`, and the emitter now handles
  list-valued ports. The **otel-collector**, which is not a `.Values.services` entry, gets a synthetic
  ClickHouse allowlist gated on `otel.exporter == clickhouse`. `webui` egress gained `identity` and
  `glea-service` (defect 5).
- **Part G** — collector runs `-contrib:0.109.0` and exports **traces and logs** to ClickHouse, mirroring
  `backend/deploy/otel/collector-config.yaml`. `debug` is retained but wired into no pipeline. New
  `otel.exporter` (`clickhouse` | `otlp`) seam repoints the whole pipeline at Tempo/Jaeger/Cloud Trace.
- `Chart.yaml` version **0.1.0 → 0.2.0** (`appVersion` untouched); description and `NOTES.txt` updated.

### Contract correction recorded during this work

The prompt guessed glea-service's env contract; `glea-service/app/config.py` overruled it on two points, and
the code won as instructed. Worth recording because the second is a governance matter, not a chart detail:

- **glea-service has no Mongo** (`config.py` declares no `MONGO_*`), so no `mongoDb` entry and no Mongo env.
- **glea-service has no authentication layer at all.** `config.py` declares no `*_AUTH_*` and no
  `*_INTERNAL_TOKEN`; `amendia_auth` is not a dependency in its `pyproject.toml` and nothing under
  `glea-service/app` imports it; every `Depends(...)` in `routers/audit.py` and `routers/cohorts.py` injects a
  reader or consumer, never a principal. Its `secretEnv` is therefore `[RABBIT_USER, RABBIT_PASSWORD]` only and
  its egress is `[rabbitmq, clickhouse, otel]` — **not** `identity`, because it makes no identity call. The
  `common: true` auth env is emitted for renderer uniformity and ignored (`extra="ignore"`).

  **Consequence, outside this ADR's scope:** the GLEA read APIs — the full audit trail, decision trails,
  lineage and cohort/SLA read-models — are unauthenticated at the service. NetworkPolicies here restrict
  *egress*, not ingress, so nothing in this chart constrains who may call them in-cluster. This is not
  introduced by chart 0.2.0 and was not fixed by it; it needs its own decision. It also contradicts the
  "Keycloak JWT (read APIs)" line the DevOps inventory carried for glea-service — corrected there on the same
  date. Route it to the ADR-065 / PII workstream or the cleanup backlog.

### Open items

- **Trap 7 is live:** the new PVC-backed datastore Deployments still use the default `RollingUpdate` strategy.
  Set `strategy: { type: Recreate }` on any datastore with a PVC, or move ClickHouse/Mongo to StatefulSets.
  Not blocking a first install (a fresh install has no old pod to block on); it bites on the first `helm upgrade`.
- ClickHouse `storage: 50Gi` is a **sizing seam, not a computed guarantee** — chosen against
  `GLEA_AUDIT_TTL_DAYS: 2555` (~7 years); real sizing is throughput × retention and is marked `# per-deployment`.
- ClickHouse remains a single-replica Deployment with no auth (`default` user, passwordless) and inherits
  `defaults.resources` (cpu 1 / mem 512Mi) — all three want revisiting before a real audit workload.
- When `datastores.clickhouse.deploy: false`, glea's `GLEA_CLICKHOUSE_HOST` and `otel.clickhouse.endpoint` must
  be overridden separately; a single `clickhouse.host` seam (as `mongo.uri` / `rabbit.host` do) would repoint
  both at once.
- `datastores.keycloak` still has no `storage` — ephemeral wherever it is deployed in-cluster (on-prem).
- `OTEL_EXPORTER_OTLP_ENDPOINT` is a hand-written special case for agent-runtime and a static `extraEnv` for
  glea-service; a `common`-level toggle would wire every telemetry-emitting service uniformly under `otel.enabled`.
- Everything above is a `helm template` / `helm lint` result. **No runtime behaviour is asserted** — there is no
  cluster, no image pull and no ClickHouse round-trip behind any of it.
