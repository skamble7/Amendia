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

---

*Started 2026-08-08 during ADR-061 review. CB-1/CB-2/CB-3 closed 2026-08-08. Owner: Sandeep.*
