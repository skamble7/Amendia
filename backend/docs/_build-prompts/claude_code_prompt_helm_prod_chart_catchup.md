# Claude Code prompt — Helm chart catch-up: GLEA + ClickHouse, real persistence, working trace export, Vault-method consistency

Chart-only change to `deploy/helm/amendia/` (+ `deploy/vault/`). The prod umbrella chart is still at the shape
ADR-022 shipped it in and has not been revised since — it predates **ADR-058 (GLEA on OTel + ClickHouse)** and
everything after it. As a result the production packaging is missing the audit system-of-record entirely, throws
its traces away, and has **no persistent storage for any datastore it deploys**. Four defects plus one egress
bug, in four independently testable phases. **No application code changes — templates, values and chart docs only.**

## Why

The gap surfaced while bringing `backend/docs/devops/Amendia_Component_Inventory_DevOps.xlsx` current. Each item
below was read-verified against the tree on 2026-08-19, not inferred:

1. **`glea-service` is not templated and ClickHouse is not deployed.** `grep -ri "glea\|clickhouse" deploy/helm/`
   returns nothing. `audit_events`, `cohort_events` and `cohort_sla_events` — the ADR-058/063/064 audit
   system-of-record — have no prod Deployment, Service, NetworkPolicy, secret path or storage plan. Everything we
   shipped from ADR-058 onward is dev-compose-only in production terms.
2. **In-cluster datastores have zero persistence.** `grep -rn "PersistentVolumeClaim\|volumeClaim\|storageClass"
   deploy/helm/amendia/templates/` returns **nothing**. `datastores.mongodb.storage: "10Gi"` and
   `global.storageClass` are declared in `values.yaml` *and set in all four provider overlays* but are consumed by
   no template. `datastores.yaml` renders a bare Deployment + Service with no volumes — so an in-cluster Mongo or
   RabbitMQ pod loses **all** data on restart or reschedule. This is the same class of defect as the missing
   RabbitMQ volume in compose, but worse: the values imply persistence that does not exist.
3. **Traces are discarded.** `otel-collector.yaml`'s ConfigMap sets `exporters: debug: {verbosity: basic}` and the
   traces pipeline exports to `[debug]` — i.e. stdout. Separately `otel.collectorImage` pins
   `otel/opentelemetry-collector:0.109.0`, the **non-contrib** image, which does not contain the ClickHouse
   exporter that `backend/deploy/otel/collector-config.yaml` relies on. Even after wiring an exporter, the pinned
   image could not run it.
4. **`vault.method` contradicts its own documentation.** `values.yaml` sets `method: "agent-injector"`;
   `deploy/vault/README.md` states *"Two delivery methods (chart `vault.method`), **CSI is the default**"*; and
   `templates/_helpers.tpl` documents CSI as the default while `secretproviderclass.yaml` renders only
   `if eq .Values.vault.method "csi"`. So the shipped default silently renders **no** SecretProviderClass.
5. **`webui`'s egress allowlist is missing two targets it actually calls.** `webui/nginx.conf` proxies
   `/api/identity/ → identity:8086` and `/api/glea/ → glea-service:8090`, but `values.services.webui.egress` lists
   only `[stub-trigger-generator, ingestor, agent-runtime, process-registry, notification-service]`. With
   `networkPolicy.defaultDenyEgress: true` those two proxy paths are blocked in production.

## Read first

- `deploy/helm/amendia/values.yaml` — the whole file, but especially `services:` (the generic per-service
  contract: `port`/`prefix`/`image`/`health`/`common`/`mongoDb`/`rabbit`/`egress`/`secretEnv`/`extraEnv`),
  `datastores:`, `otel:`, `vault:`, `networkPolicy:`, `global.storageClass`.
- `deploy/helm/amendia/templates/_helpers.tpl` — `amendia.commonEnv` (note it emits `_MONGO_URI` only when
  `mongoDb` is set, and `_RABBITMQ_URL` only when `rabbit: true` — so a rabbit-but-no-mongo service like
  glea-service is already expressible), `amendia.secretEnv`, `amendia.vaultAnnotations`, `amendia.svc`,
  `amendia.image`.
- `deploy/helm/amendia/templates/deployment.yaml`, `service.yaml`, `pdb.yaml`, `secretproviderclass.yaml`,
  `networkpolicy.yaml` — **all five `range` over `.Values.services`**, so adding one entry to that map renders a
  Deployment, Service, PDB, SecretProviderClass and egress NetworkPolicy with no template edits. Confirm this
  before writing any new template.
- `deploy/helm/amendia/templates/networkpolicy.yaml` — the `$ports` dict (token → in-cluster port) near the top;
  new egress targets must be registered there or the allowlist entry is silently skipped.
- `deploy/helm/amendia/templates/datastores.yaml` — the `range` over `.Values.datastores` and its hardcoded
  `$port` switch (`27017` default, `5672` rabbitmq, `8080` keycloak). This is where ClickHouse and the PVCs go.
- `deploy/helm/amendia/templates/otel-collector.yaml` — the ConfigMap + Deployment.
- `deploy/helm/amendia/values-{gke,eks,aks,onprem}.yaml` — each already sets `global.storageClass`; check what
  else each overlay pins before adding to them.
- `backend/services/platform/glea-service/app/config.py` — **authoritative** for glea's env contract. Derive the
  env names from here, do not copy them from this prompt or from compose. Cross-check against the
  `glea-service` block in `backend/deploy/docker-compose.yml`.
- `backend/deploy/otel/collector-config.yaml` — the working ClickHouse exporter config to mirror (note the
  `tcp://clickhouse:9000?dial_timeout=10s&compress=lz4` native endpoint and the `otel` database).
- `deploy/vault/README.md` + `policy.hcl` — the method wording and the bound-ServiceAccount list.

## Deliverables

### Phase 1 — Trace export that actually exports (`otel-collector.yaml`, `values.yaml`)

1. Change `otel.collectorImage` to the **contrib** distribution
   (`otel/opentelemetry-collector-contrib:0.109.0` — match the tag compose uses).
2. In the ConfigMap, replace the `debug` exporter with a **ClickHouse exporter** mirroring
   `backend/deploy/otel/collector-config.yaml` (same database/table conventions, endpoint built from the
   ClickHouse Service name and the release name via `amendia.svc`). Keep `debug` available but **not** in the
   pipeline, or gate it behind a values flag — do not leave a stdout-only pipeline as the default.
3. Add a `logs` pipeline alongside `traces` if compose has one and the exporter supports it (compose does — check).
4. Make the exporter target configurable: a values seam so a deployment can point at Tempo/Jaeger/Cloud Trace
   instead, with ClickHouse as the default now that GLEA depends on it. Keep the existing
   `# per-deployment` comment convention.

**Testable on its own:** `helm template` renders a collector ConfigMap whose traces pipeline exports to
ClickHouse, and the Deployment pulls the `-contrib` image.

### Phase 2 — Vault method consistency (`values.yaml` or `deploy/vault/README.md`)

5. Resolve defect 4 by making `values.yaml` and `deploy/vault/README.md` agree. **Pick CSI as the default**
   (`vault.method: "csi"`) — that is what `_helpers.tpl`, `secretproviderclass.yaml` and the README all already
   assume, and it is the one that renders a working secret path out of the box. Update any prose in `values.yaml`
   or `NOTES.txt` that still implies agent-injector is the default. Leave agent-injector fully functional as the
   documented alternative; do not delete it.

**Testable on its own:** `helm template` with default values now renders one `SecretProviderClass` per service;
switching to `agent-injector` renders the pod annotations instead and no SecretProviderClass.

### Phase 3 — Real persistence for in-cluster datastores (`datastores.yaml`, `values.yaml`, overlays)

6. Make `global.storageClass` and `datastores.<name>.storage` **load-bearing**. For each datastore with
   `deploy: true` and a `storage` value, render a `PersistentVolumeClaim` (`ReadWriteOnce`, size from
   `storage`, `storageClassName` from `global.storageClass` — omit the field entirely when the value is `""` so
   the cluster default applies) and mount it at the correct data path on the Deployment:
   - mongodb → `/data/db`
   - rabbitmq → `/var/lib/rabbitmq`  (**add `storage` to `datastores.rabbitmq` in values — it has none today**;
     this is the Helm counterpart of the missing compose volume and matters for the GLEA audit queue)
   - clickhouse → `/var/lib/clickhouse` (Phase 4)
   A datastore with no `storage` value (or `deploy: false`) renders no PVC and no volume — keep that path working
   so a BYO/managed deployment is unaffected.
7. Replace the hardcoded `$port` switch with a small port map (mirroring `networkpolicy.yaml`'s `$ports`) so
   adding a datastore does not mean editing an `if/else` chain. ClickHouse needs **two** ports (8123 HTTP, 9000
   native) — make the map support a list, or handle multi-port datastores explicitly.
8. Set a sensible default `storage` for rabbitmq in `values.yaml` and confirm the four provider overlays still
   make sense (they already set `global.storageClass`; add per-provider notes only where genuinely needed).

**Testable on its own:** `helm template` renders a PVC + volumeMount for mongodb and rabbitmq; setting
`datastores.mongodb.deploy=false` renders neither; setting `global.storageClass=""` omits `storageClassName`.

### Phase 4 — GLEA + ClickHouse in the chart (`values.yaml`, `datastores.yaml`, `networkpolicy.yaml`)

9. **Add `clickhouse` to `datastores`** — `deploy: true`, `image: clickhouse/clickhouse-server:24.8` (match
   compose), ports 8123 + 9000, and a `storage` default sized for a multi-year audit TTL (propose a value and say
   why in the report; it should be visibly larger than mongo's 10Gi). Follow the same "disable and point external
   in prod" convention as the other datastores, and add the standard `# per-provider` / `# per-deployment` seams.
10. **Add `glea-service` to `values.services`** so the five generic renderers pick it up with no new template.
    Derive the env contract from `glea-service/app/config.py`; expected shape (verify each field, correct me
    where I'm wrong):
    - `port: 8090`, `image: glea-service`, `health: /health`, `common: true`, `rabbit: true`, **no `mongoDb`**
      (glea has no Mongo — confirm), ClickHouse settings via `extraEnv`, `egress: [rabbitmq, clickhouse, identity]`,
      and `secretEnv` covering its internal token + `RABBIT_USER`/`RABBIT_PASSWORD` (match the naming the other
      services use).
    - Keep the prod-hardening posture the other services get (no dev CORS, no debug/seed APIs — check whether
      glea has equivalents).
11. **Register the new egress tokens** in `networkpolicy.yaml`'s `$ports` dict: `clickhouse` → 8123 (add 9000 too
    if the collector uses the native port — it does; make sure the rule covers what is actually dialled) and
    `glea-service` → 8090. An unregistered token is silently dropped from the allowlist, so verify the rendered
    NetworkPolicy actually contains the rules.
12. **Add the otel-collector's egress to ClickHouse.** The collector now dials ClickHouse; under
    `defaultDenyEgress` it needs its own allowlist. It is not in `.Values.services`, so check how (or whether)
    `networkpolicy.yaml` covers it today and add a rule.
13. **Fix defect 5:** add `identity` and `glea-service` to `values.services.webui.egress`. Confirm against
    `webui/nginx.conf` that the full proxy target list is covered and nothing else is missing.
14. **Vault:** add `secret/data/amendia/glea-service` to `deploy/vault/policy.hcl` and add the glea-service
    ServiceAccount to the `bound_service_account_names` list in `deploy/vault/README.md`'s role command.
15. Update `templates/NOTES.txt` and `Chart.yaml`'s description if they enumerate services (both do — check), and
    bump `Chart.yaml` `version` (chart version only; leave `appVersion` alone).

**Testable on its own:** `helm template` renders a glea-service Deployment/Service/PDB/SecretProviderClass/
NetworkPolicy, a ClickHouse Deployment/Service/PVC, and a webui egress policy that includes identity and
glea-service.

## Do not

- **Do not touch any application code.** No `backend/services/**`, no `webui/src/**`, no `libs/**`. If a chart
  change appears to require an app change, stop and write it up in the report instead.
- Do not modify `backend/deploy/docker-compose.yml` or the compose otel config — the dev stack is correct and is
  the reference this work copies *from*. (The missing compose RabbitMQ volume is a known separate item; leave it.)
- **Do not write or edit any ADR.** ADRs are Claude's to author; the ADR-022 revision note is being handled
  separately. Reference ADR numbers in comments, do not create them.
- Do not change `executionMode`, `nemoclawRequired`, the inference/NIM block, or the OpenShell sandbox gate —
  all out of scope, and the NIM/OpenShell `# [confirm] + STOP` markers stay untouched.
- Do not restructure the generic renderer. The point of Phase 4 is that adding a service is a **values** change;
  if you find yourself writing a `glea-service.yaml` template, the values entry is wrong — fix that instead.
- Do not delete the agent-injector Vault path.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- `helm lint deploy/helm/amendia` clean, and `helm template` succeeds with **each** of the four overlays
  (`values-gke.yaml`, `values-eks.yaml`, `values-aks.yaml`, `values-onprem.yaml`) plus bare defaults.
- Rendered output with defaults contains: a `glea-service` Deployment + Service + PDB + SecretProviderClass +
  egress NetworkPolicy; a ClickHouse Deployment + Service + PVC; PVCs for mongodb and rabbitmq with the right
  mount paths; an otel-collector ConfigMap exporting to ClickHouse on the `-contrib` image; a `webui` egress
  policy naming identity and glea-service.
- `global.storageClass: ""` renders PVCs **without** a `storageClassName` field (cluster default), not with an
  empty string.
- `datastores.{mongodb,rabbitmq,clickhouse}.deploy: false` renders no Deployment, Service or PVC for that
  datastore, and the services still render pointing at the external endpoints from values.
- `vault.method: "csi"` (new default) renders SecretProviderClasses; `agent-injector` renders pod annotations and
  no SecretProviderClass. Both still render cleanly.
- Every env var name added is traceable to `glea-service/app/config.py` — quote the file/line for each in the
  report.
- **Reviewer note:** state explicitly which parts you verified by rendering vs. by reading. A `helm template`
  diff is the evidence here; there is no running cluster to prove it against, so do not claim runtime behaviour.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_helm_prod_chart_catchup_report.md` (uncommitted):
(1) outcome one-liner; (2) changes by file, phase by phase; (3) decisions & deviations — in particular the
ClickHouse `storage` size you chose and why, how you handled multi-port datastores, and anything in my Phase 4
env-contract guess that `config.py` contradicted; (4) what you deliberately left alone (compose, ADRs, app code,
NIM/OpenShell); (5) verification — the exact `helm lint` / `helm template` commands per overlay and their
results, plus a short list of the key rendered objects you confirmed by eye; (6) follow-ups — anything the chart
still lacks for a real production handover that was out of this prompt's scope. One to two screens.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Chart, values, Vault config and chart docs only; no
application code, no compose, no ADRs. Reuse the existing generic renderer and the `# per-provider` /
`# per-deployment` comment seams rather than adding one-off templates. Where this prompt guesses at glea's env
contract, `glea-service/app/config.py` wins — say so in the report rather than making the code match the prompt.
