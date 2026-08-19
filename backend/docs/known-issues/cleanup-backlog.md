# Cleanup backlog — small DB/residue items

A living list of small, low-urgency issues (stray collections, orphaned rows, residue from past ADRs) found
during review. Not architectural decisions — each is a bounded cleanup. Add new items at the bottom with the
next `CB-##`; keep the finding honest (verified vs suspected) so the fix scope is clear.

Status legend: `open` · `investigating` · `fix-prompted` · `done` · `wontfix`.

---

## ~~CB-1 — Orphaned onboarding-draft BPMN in `bpmn_documents` (`__onb__…` keys)~~ — **DONE (2026-08-08)**

- **Area:** process-registry · `bpmn_documents`
- **Observed (Compass):** rows keyed `pack_key = "__onb__onb-<session>"` (e.g. `__onb__onb-a86663148dbe`,
  versions 1.0.0 / 1.1.0) remained after packs came and went.
- **Finding:** ADR-061 delete **does** remove a committed pack's BPMN. These leftovers were a **separate** issue:
  onboarding stored the draft BPMN under a temporary `__onb__<session>` pack key and nothing garbage-collected
  it — not commit, not `DELETE /onboarding/{session}`, not pack delete (different key). Draft BPMN accumulated
  per onboarding session.
- **Severity:** low (inert scratch; never loaded by the runtime, which reads by real pack key).
- **Fix delivered:** three-part in process-registry — staging row dropped on session-delete
  (`onboarding.py:259`), on successful commit (`onboarding.py:1203`), and a fail-soft one-time startup sweep
  (`purge_orphaned_staging_bpmn`, wired in `main.py:53-62`) that clears absent/committed orphans but spares
  in-progress drafts. New `test_cb1_staging_bpmn_cleanup.py` + extended commit e2e assertion. Verified: no
  `__onb__` orphan survives commit/delete/sweep.

## ~~CB-2 — `capability_memo` rows for a deleted pack's instances (NOT a pack-delete gap)~~ — **ACCEPTED BY DESIGN (`wontfix`, 2026-08-08)**

- **Area:** agent-runtime · `capability_memo`
- **Observed:** rows keyed by `process_instance_id` (e.g. `pi-036f3d1ebab54936::Enrich::…`) persist after a pack
  is deleted.
- **Finding (confirmed):** the collection **is** used — ADR-019 per-instance capability memoization (runtime-private,
  crash-durable, scoped by `process_instance_id`). It is **runtime instance** data, not registry/pack data.
  ADR-061 pack deletion deliberately does **not** touch runtime instances, checkpoints, or memos (force-delete
  strands in-flight instances by design). `delete_versions` touches only registry rows and has zero references
  to runtime memos/instances (different service/DB). Memos for a deleted pack's instances are orphaned-but-inert
  — expected, not a bug.
- **Disposition:** accept by design. Retaining an instance's runtime/audit trail after its pack is deleted is
  reasonable (the instances *did* run). Purging would be a separate cross-service **instance-GC** feature
  (registry→runtime coordination reacting to `PackLifecycleEvent op=delete`) and would need its own ADR — still
  **Sandeep's call** whether to build it.

## ~~CB-3 — `sample_exceptions` domain-naming residue~~ — **DONE via rename (2026-08-08)**

- **Area:** agent-runtime (`seeding/load.py`, `SAMPLE_EXCEPTIONS`, `SampleExceptionRepository`) + process-registry
  (`packs.py::_load_sample_envelopes`; `validation/pack_validator.py`) + shared seed/fixture dirs.
- **Finding (corrected on review — NOT dead):** the sample envelopes were still used. `declare_trigger` is an
  **optional** enrichment, so no-trigger packs are supported and rely on `infer_field_types(samples)` as the
  authoritative triage field source; the samples also drive the picker default and an informational smoke test
  on same-domain declared-trigger packs. The file was also a test fixture in ~5 suites. So the samples were
  **not removable** — the only real issue was the residual `exception` domain term (ADR-059 leak).
- **Fix delivered:** careful **cross-service rename** — `sample_exception(s)`→`sample_trigger(s)`,
  `sample-exception`→`sample-trigger`, plus identifiers — across both services + all three shared seed/fixture
  dirs (the shared-dir coordination the reverted ADR-059 follow-up got wrong), plus three methodology-doc
  references. Sample file **contents** kept as wire-domain data. Verified: process-registry 366 passed,
  agent-runtime 343 passed / 4 skipped; token sweep clean outside historical ADR/build artifacts.
- **Open follow-up (optional, Sandeep's call):** the rename was necessary only because `declare_trigger` is
  optional and the inference fallback is still reachable. If the intent is that **no pack should ever commit
  without a declared trigger**, making `declare_trigger` mandatory at assemble would make the sample-inference
  fallback genuinely dead and removable. That is a behavioural/contract change (an ADR, not a cleanup) — tracked
  as **CB-4** below.

## ~~CB-4 — Make `declare_trigger` mandatory at assemble?~~ — **PARKED (`wontfix`, 2026-08-08)**

- **Area:** process-registry onboarding/assemble contract · relates ADR-047/049 (domain-neutral trigger schema).
- **Context:** surfaced by CB-3. Today `declare_trigger` is optional enrichment; no-trigger packs fall back to
  `infer_field_types(sample_envelopes)` for triage. If declared triggers were **required**, the sample-inference
  path becomes dead code and the `sample_trigger` seed/fixture machinery could be deleted outright.
- **Decision (Sandeep, 2026-08-08):** **keep `declare_trigger` optional.** The optional-trigger + sample-inference
  path is the deliberate low-bar onboarding of ADR-047/049; forcing a declared trigger would regress no-trigger
  packs and cut against domain-neutrality. The CB-3 rename already neutralized the vocabulary, so the fallback is
  a clean, supported path — not residue. Not pursuing. Re-open only if the onboarding contract is revisited.

## CB-5 — webui generated API types need re-sync (`npm run gen:api`) — **OPEN (operational)**

- **Area:** webui · `src/api/gen/*` (OpenAPI-generated types).
- **Context:** ADR-063 Phase 2 + Phase 3A/3B re-dumped several OpenAPI snapshots (registry cohort-definition +
  membership routes, `/resolve` discriminated `kind`, `/packs/{key}/{ver}/trigger-fields`, the instance
  cohort-backlink fields). CC regenerated `gen/registry.ts` **offline** so `tsc` is clean, but
  `npm run gen:api:check` regenerates **all** services and needs the live compose stack — so the generated
  types can drift from the running APIs until a full regen is run against the stack.
- **Severity:** low (build/DX only; typecheck currently passes on the offline-regenerated registry types).
- **Action (operator, needs the stack up):** `cd webui && npm run gen:api && git add src/api/gen`, then confirm
  `npm run gen:api:check` is green. Not a code change. (Related, separate operator step: rebuild
  `process-registry` after commit so the wire-screen type-compat guard — Fix 2, still uncommitted — goes live.)
- **Status:** `open` (operational; clears once run against the stack).

## CB-6 — Cohort membership stamped in-place vs version-gated — **OPEN (decision)**

- **Area:** process-registry · `PUT/DELETE /packs/{pack_key}/{version}/cohort-membership` (ADR-063 Phase 2).
- **Context:** assigning/clearing a pack's `cohort_membership` mutates that pack version's stored manifest
  **in place** — no new pack version is cut. Rationale taken during Phase 2: membership is additive
  **observational** metadata that does not change execution, so it doesn't warrant a version bump. The
  trade-off is that it mutates the manifest of an already-active pack version.
- **Decision needed (Sandeep's call):** keep **in-place** (current, simplest) OR make membership changes
  **version-gated** (clone-to-new-version, à la ADR-056 pack-config editing) if pack manifests must be
  immutable once active. Default = keep in-place unless manifest immutability is a hard requirement.
- **Severity:** low (no functional problem today; a governance/immutability preference).
- **Status:** `open` (decision; not blocking).

## CB-7 — Cohort SLA alerting (owner-routed email/push) — **OPEN (deferred by decision)**

- **Area:** a *new* independent consumer of `agent_runtime.cohort_sla.v1`, plus the platform's first outbound
  alert channel (notification-service or a sibling).
- **Context:** ADR-064 V1 is deliberately **surface-only** — a breach or at-risk shows as a UI badge plus a thin
  SSE invalidation signal. There is **no email, push or webhook sender anywhere in the platform** (re-verified
  2026-08-19: nothing under `notification-service/app` matches `slack|teams|smtp|sendgrid|email`; the
  `signal_mapper` allow-list → `hub` → `GET /stream` path is the only outbound route). Alerting is therefore
  net-new work, not a config toggle.
- **Shape if picked up:** a separate consumer of the existing SLA event stream, routed by the breach's owner
  attribution (`external` | `amendia` | `shared`). **Zero rework to ADR-064 P2–P4** — the stream already carries
  what is needed.
- **Severity:** low under the current observe-first stance; rises the moment a breach must reach someone who is
  not watching the board.
- **Status:** `open` (deferred by Sandeep 2026-08-12 — observe first). Likely warrants its own small ADR when
  picked up, since it introduces an outbound channel the platform has never had.

## CB-8 — ADR-064 P4 follow-ups: pending-plan snapshot + SLA-editor UX — **OPEN**

- **Area:** agent-runtime (new read API) · webui (`SlaGraphEditor`, `SlaPanel`).
- **Context:** GLEA surfaces **transition-derived** SLA state only (`at_risk`/`breached`/`satisfied`/`voided`).
  Still-*pending* expectations live in the agent-runtime `cohort_sla_expectations` snapshot — the SoR — which has
  no REST surface, so the UI cannot render a full "what is still expected, with countdowns" plan.
- **Items:** (a) an agent-runtime snapshot endpoint exposing pending expectations + `due_at`; (b) friendlier
  duration entry in the SLA editor (raw seconds today); (c) a visual DAG canvas — V1 is a tabular editor and the
  canvas was explicitly scoped out of ADR-064.
- **Severity:** low (feature completeness, not correctness).
- **Status:** `open`.

## CB-9 — `glea-service` has no authentication layer — **OPEN (security)**

- **Area:** glea-service · `app/routers/{audit,cohorts}.py`, `app/config.py`, `pyproject.toml`.
- **Finding (verified 2026-08-19 by reading the source — not suspected):** glea-service mounts **no auth at
  all**. `config.py` declares no `*_AUTH_*` and no `*_INTERNAL_TOKEN`; **`amendia_auth` is not a dependency in
  its `pyproject.toml`** and nothing under `glea-service/app` imports it; every `Depends(...)` in `audit.py` and
  `cohorts.py` injects an `AuditReader`/`CohortReader`/`AuditSealer`/`AuditConsumer` — never a principal. This
  makes glea the **only** Amendia service without the ADR-012 baseline ("every endpoint requires a valid OIDC
  bearer except `/health`").
- **Exposure:** the entire GLEA read surface is open to anything that can reach the service — instance audit,
  decision trails, lineage, trace trees, metrics, seal verification, and the ADR-063/064 cohort + SLA
  read-models. In compose it is published on host **18090** and proxied by the webui nginx at `/api/glea/`. In
  Helm (chart 0.2.0) the NetworkPolicies govern **egress**, not ingress, so nothing restricts it there either.
- **Why this is not an ordinary cleanup item:** `audit_events.payload` stores the **entire raw event JSON
  verbatim** under a ~7-year TTL (`GLEA_AUDIT_TTL_DAYS: 2555`), so this is an unauthenticated read path onto the
  platform's most sensitive store. It also contradicted the "Keycloak JWT (read APIs)" line the DevOps inventory
  carried until 2026-08-19 — i.e. the gap was invisible in the documentation, which is how it survived.
- **Not a regression:** it has been this way since ADR-058. It surfaced during the ADR-022 chart catch-up, when
  glea's env contract had to be derived from `config.py` to write its Helm values entry.
- **Action (decision needed):** (a) mount `amendia_auth` with a baseline principal + a read role, matching every
  sibling service — the consistent answer; or (b) declare glea explicitly **internal-only** and enforce that at
  the network layer (no published port, no webui proxy, ingress policy) — a stopgap that leaves the service
  itself trusting.
- **Cross-refs:** ADR-012 (baseline enforcement), ADR-058, the ADR-022 chart-0.2.0 revision (§ Contract
  correction), and `amendia_pii_processor_gap_analysis.md` (adjacent to G-34 "no field-read access log" and G-07
  standing RBAC).
- **Severity:** **high** — recorded here for tracking, but this is not a low-urgency residue item. Against real
  customer data it is a go-live blocker, not a cleanup.
- **Status:** `open` (security decision).

---

*Started 2026-08-08 during ADR-061 review. CB-1/CB-2/CB-3 closed and CB-4 parked 2026-08-08.
CB-5 (operational) + CB-6 (decision) opened 2026-08-08. CB-7/CB-8 were tracked in the working-model bridge notes
from 2026-08-12 but had never been written into this file — restored 2026-08-19 so this register is the single
on-disk source. CB-9 opened 2026-08-19 during the ADR-022 chart catch-up review. Owner: Sandeep.*
