# Helm chart catch-up — GLEA + ClickHouse, real persistence, working trace export, Vault consistency

**Outcome.** The prod umbrella chart now packages the ADR-058 audit system-of-record (GLEA + ClickHouse), gives
every in-cluster datastore PVC-backed persistence, exports traces to ClickHouse on the contrib collector image, and
ships a Vault default that actually renders a secret path — five defects + one egress bug closed, **chart/values/Vault
only, no application code**. Verified by `helm lint` (clean) and `helm template` (exit 0) across bare defaults + all
four overlays.

## Changes by file (phase by phase)

### Phase 1 — trace export that exports (`values.yaml`, `templates/otel-collector.yaml`)
- `otel.collectorImage`: `otel/opentelemetry-collector:0.109.0` → **`-contrib:0.109.0`** (the non-contrib image has
  no ClickHouse exporter).
- New `otel.exporter` (`clickhouse` default | `otlp`), `otel.exporterEndpoint`, and `otel.clickhouse.{endpoint,
  database,ttl}` seams in `values.yaml`.
- `otel-collector.yaml` ConfigMap: replaced the stdout-only `debug` pipeline with a **ClickHouse exporter** mirroring
  `backend/deploy/otel/collector-config.yaml` (`tcp://<release>-clickhouse:9000?dial_timeout=10s&compress=lz4`,
  `database: otel`, `create_schema: true`, `ttl`, `otel_traces`/`otel_logs`, `retry_on_failure`). Both **`traces`
  and `logs`** pipelines export to the selected exporter. `debug` is retained but **not** wired into any pipeline.
  `exporter: otlp` swaps in an OTLP exporter pointed at `exporterEndpoint` (Tempo/Jaeger/Cloud-Trace).

### Phase 2 — Vault method consistency (`values.yaml`)
- `vault.method`: `agent-injector` → **`csi`** (now agrees with `_helpers.tpl`, `secretproviderclass.yaml`,
  `deploy/vault/README.md`, and all four overlays, which already set `csi`). Comment rewritten; agent-injector kept
  as the documented alternative. `NOTES.txt` already prints `vault.method` dynamically, so it now reads `csi`.

### Phase 3 — real persistence (`values.yaml`, `templates/datastores.yaml`)
- `datastores.yaml` rewritten: a `$dsPorts` map (mongodb 27017, rabbitmq 5672, keycloak 8080, **clickhouse [8123,
  9000]**) replaces the hardcoded `if/else` port switch, and a `$dsDataPath` map drives a **PersistentVolumeClaim**
  (RWO, size from `storage`, `storageClassName` from `global.storageClass` — **omitted entirely when `""`**) +
  volumeMount for any `deploy:true` datastore that has a `storage` value. Mounts: mongodb `/data/db`, rabbitmq
  `/var/lib/rabbitmq`, clickhouse `/var/lib/clickhouse`. No `storage` (or `deploy:false`) ⇒ no PVC/volume (unchanged).
- `values.yaml`: added **`storage: "8Gi"` to `datastores.rabbitmq`** (had none — the Helm counterpart of the missing
  compose volume; the durable GLEA audit queue now survives restarts).

### Phase 4 — GLEA + ClickHouse in the chart (`values.yaml`, `templates/networkpolicy.yaml`, `deploy/vault/*`, `Chart.yaml`, `NOTES.txt`)
- **`datastores.clickhouse`** added (`deploy:true`, `clickhouse/clickhouse-server:24.8`, ports 8123+9000, `storage:
  "50Gi"`) — renders a Deployment/Service (both ports) + PVC via the generic datastore renderer.
- **`services.glea-service`** added → the five generic renderers emit Deployment/Service/PDB/SecretProviderClass/
  egress-NetworkPolicy + a ServiceAccount, **no new template**.
- `networkpolicy.yaml`: `$ports` gained `glea-service: 8090` and `clickhouse: [8123, 9000]`; the egress emitter now
  handles **list-valued** ports; the **otel-collector** (not a `services` entry) gets a synthetic egress allowlist to
  ClickHouse when it's deployed and exporting there.
- **webui egress** (`values.yaml`): added `identity` + `glea-service` (defect 5 — both are proxied in
  `webui/nginx.conf` but were blocked under default-deny).
- `deploy/vault/policy.hcl`: `read` on `secret/data/amendia/glea-service`. `deploy/vault/README.md`: glea SA added to
  `bound_service_account_names`, plus a `vault kv put …/glea-service RABBIT_USER RABBIT_PASSWORD` example.
- `Chart.yaml`: description now lists glea-service + ClickHouse; **`version` 0.1.0 → 0.2.0** (`appVersion` untouched).
  `NOTES.txt`: new "Audit / traces" line (GLEA SOR + OTel → ClickHouse).

## Decisions & deviations

- **ClickHouse `storage: 50Gi`.** ClickHouse holds two very different horizons: 72h of `otel_traces`/`otel_logs`
  (trivial) and GLEA's **~7-year** `audit_events` SOR (`GLEA_AUDIT_TTL_DAYS: 2555`, config.py:35). 50Gi is a
  deliberately-larger-than-Mongo (10Gi) starting point — audit rows are compact and columnar-compressed, but real
  sizing is throughput × 7yr, so it's marked `# per-deployment`. Not a computed guarantee; a sizing seam.
- **Multi-port datastore/token.** Handled explicitly (not by forcing every entry to a list): `$dsPorts`/`$ports`
  values may be a scalar **or** a list; the datastore renderer ranges the list for container/Service ports, and the
  netpol egress emitter branches on `kindIs "slice"`. ClickHouse is the only multi-port entry (8123 HTTP for GLEA,
  9000 native for the collector).
- **glea env-contract corrections vs. the prompt's guess** (config.py + compose win, as instructed):
  - **No internal-auth token.** `glea-service/app/config.py` has **no** `*_INTERNAL_TOKEN` field and no auth/JWKS
    settings at all; `rg` over `glea-service/app` finds no `amendia_auth`/identity/token-verify usage. So `secretEnv`
    is **`[RABBIT_USER, RABBIT_PASSWORD]`** only — the prompt's "internal token" does not exist. The `common:true`
    auth env (`GLEA_AUTH_*`) is emitted for sibling-consistency but **ignored** by glea (`extra="ignore"`,
    config.py:53); it buys `GLEA_LOG_LEVEL` + the `$(…)`-interpolated `GLEA_RABBITMQ_URL` from the shared helper.
  - **egress: `[rabbitmq, clickhouse, otel]`, NOT `identity`.** glea makes no identity call (config.py has no
    identity env; compose has none either), so `identity` was dropped as an unused allow. Conversely glea **does**
    export OTLP — `app/main.py` calls `configure_telemetry("glea-service")` and compose sets
    `OTEL_EXPORTER_OTLP_ENDPOINT` — so `otel` was **added** (the prompt's list omitted it). `OTEL_EXPORTER_OTLP_ENDPOINT`
    is set via `extraEnv` (config.py `CLICKHOUSE_PORT: 8123` = HTTP, matched in extraEnv).
  - **No Mongo** — confirmed (config.py has no `MONGO_*`); `mongoDb` omitted, so the helper emits no mongo env.
- **glea's ClickHouse egress allows both 8123 and 9000** (the shared `clickhouse` token) though glea only dials 8123.
  A one-port-over minor over-permission to the *same* datastore, in exchange for a single reusable token; flagged
  rather than special-cased per consumer.
- **`OTEL_EXPORTER_OTLP_ENDPOINT` for glea is a static `extraEnv` value** (`http://amendia-otel-collector:4318`, =
  the `otel.endpoint` default) rather than gated on `otel.enabled` like agent-runtime's. agent-runtime's is a
  hand-written special-case in `deployment.yaml`; adding one for glea would violate "adding a service is a *values*
  change." The static value is correct for the default topology; see follow-ups.

## Deliberately left alone
- **No application code** (`backend/services/**`, `webui/src/**`, `libs/**`) — untouched.
- **No compose / compose otel config** — it is the reference this work copied *from*. The known missing compose
  RabbitMQ volume was left as its separate item.
- **No ADRs** created or edited.
- `executionMode` / `nemoclawRequired` / the `inference`/NIM block / the OpenShell sandbox gate and their
  `# [confirm] + STOP` markers — untouched.
- The generic renderer was **not** restructured; glea-service is a pure values entry (no `glea-service.yaml`).
- No git writes — tree left dirty.

## Verification (rendered, not run — there is no cluster)

Commands (all from repo root, `helm` v3):
```
helm lint deploy/helm/amendia                                             # clean (0 failed)
helm lint deploy/helm/amendia -f deploy/helm/amendia/values-{gke,eks,aks,onprem}.yaml   # each: 0 failed
helm template amendia deploy/helm/amendia                                 # exit 0, 74 objects
helm template amendia deploy/helm/amendia -f …/values-{gke,eks,aks,onprem}.yaml         # each exit 0
```
Toggle checks (all `helm template --set …`, confirmed):
- `vault.method=agent-injector` → **0** SecretProviderClass, **10** `agent-inject` annotations; CSI default → **8**
  SecretProviderClass.
- `datastores.mongodb.deploy=false` → **0** `amendia-mongodb` objects, PVCs 3→2, services still carry
  `mongodb://amendia-mongodb:27017` (external URI path intact).
- `datastores.clickhouse.deploy=false` → **0** clickhouse objects.
- `otel.exporter=otlp --set otel.exporterEndpoint=tempo:4317` → OTLP exporter rendered, `traces`+`logs → [otlp]`,
  collector→ClickHouse egress rule correctly suppressed.
- `global.storageClass=""` (onprem + default) → PVCs render **without** `storageClassName`; gke/eks/aks →
  `standard-rwo`/`gp3`/`managed-csi` respectively.

Key rendered objects confirmed **by eye** (defaults): glea-service Deployment (image `…/glea-service:0.1.0`; env
`GLEA_LOG_LEVEL`, `GLEA_RABBITMQ_URL`, `GLEA_CLICKHOUSE_{HOST,PORT,DB,USER,TABLE,COHORT_TABLE,COHORT_SLA_TABLE}`,
`GLEA_ENABLE_DEV_CORS=false`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `RABBIT_USER/PASSWORD` via `secretKeyRef`; **no**
`GLEA_MONGO_*`); ClickHouse Deployment (containerPorts 8123+9000, mount `/var/lib/clickhouse`, claim
`amendia-clickhouse-data`) + Service (p8123/p9000) + PVC (50Gi, RWO); mongodb PVC (10Gi, `/data/db`) + rabbitmq PVC
(8Gi, `/var/lib/rabbitmq`); collector ConfigMap (clickhouse exporter → `tcp://amendia-clickhouse:9000…`, traces+logs
pipelines) on the `-contrib` image; glea egress netpol (rabbitmq:5672, clickhouse:8123+9000, otel-collector:4318);
otel-collector egress netpol (clickhouse:8123+9000); webui egress netpol (…, identity, glea-service, …).

**Claim boundary:** this is a `helm template`/`lint` diff only — no runtime behaviour is asserted (no cluster, no
image pulls, no ClickHouse round-trip).

## Follow-ups (out of this prompt's scope)
1. **Managed-ClickHouse ergonomics.** When `datastores.clickhouse.deploy=false`, glea's `GLEA_CLICKHOUSE_HOST` and
   `otel.clickhouse.endpoint` still default to the in-cluster Service; a managed CH needs both overridden. Consider a
   single `clickhouse.host`/`clickhouse.uri` values seam the way `mongo.uri`/`rabbit.host` work, so one override
   repoints glea + collector together.
2. **ClickHouse auth.** `GLEA_CLICKHOUSE_PASSWORD` / a collector CH password is not wired to Vault (the in-cluster
   `default` user is passwordless). A managed CH needs `GLEA_CLICKHOUSE_PASSWORD` in `secretEnv` + a Vault key.
3. **Generalise OTLP wiring.** `OTEL_EXPORTER_OTLP_ENDPOINT` is special-cased for agent-runtime and static for glea;
   a `common`-level toggle would wire every telemetry-emitting service uniformly (and follow `otel.enabled`).
4. **ClickHouse is single-replica, no StatefulSet.** Fine for a pilot/self-contained stack; a production audit SOR
   wants a StatefulSet (stable identity, ordered volumes) or a managed/operator ClickHouse.
5. **Keycloak persistence.** `datastores.keycloak` still has no `storage` (ephemeral when `deploy:true`, e.g.
   on-prem); out of this prompt's mongo/rabbit/clickhouse scope but worth a PVC or an external DB for real use.
6. **ClickHouse resources.** It inherits `defaults.resources` (cpu 1 / mem 512Mi) — likely too small under real audit
   load; add a per-datastore resources seam.
