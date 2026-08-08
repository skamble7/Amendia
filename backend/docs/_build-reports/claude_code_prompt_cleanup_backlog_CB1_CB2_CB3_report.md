# Cleanup backlog — CB-1 / CB-2 / CB-3: report

Three independent items from `backend/docs/known-issues/cleanup-backlog.md`, kept separable in the diff.

| Item | Disposition |
|------|-------------|
| CB-1 | **Done** — orphaned `__onb__<session>` staging BPMN now purged on commit, on session-delete, and by a one-time startup sweep. |
| CB-2 | **Accepted by design** — `capability_memo` is per-instance (ADR-019), runtime-private; ADR-061 pack deletion deliberately never touches runtime instances/memos. No code change. |
| CB-3 | **Rename (neutralize), not removal** — the sample fallback is a *supported, live* path, so per the task's guard the `sample_exception(s)` / `sample-exception` vocabulary was neutralized to `sample_trigger(s)` / `sample-trigger` across **both** services + the shared seed dirs. |

---

## CB-1 — purge orphaned onboarding-draft BPMN (`__onb__<session>`)

**Problem.** Onboarding stages draft BPMN under a per-session key `_staging_pk(s) = "__onb__" + s.session_id`.
Commit re-keys it to the real pack and session-delete drops the session, but neither removed the staging row, so
`bpmn_documents` accumulated `__onb__…` rows forever.

**Fix (three parts, all in process-registry).**

1. **On session delete** — [`onboarding.py:259`](../../services/process-registry/app/services/onboarding.py#L259):
   `delete()` now calls `await self.bpmn.delete_pack(self._staging_pk(s))` after removing the session (idempotent
   `delete_many`).
2. **On commit** — [`onboarding.py:1203`](../../services/process-registry/app/services/onboarding.py#L1203):
   after a **fully successful** commit (state → `COMPLETED`, real-key BPMN written at step 4), the staging row is
   dropped. Placed after the success point on purpose — a failed commit raises earlier and keeps the staging row so
   a retry still finds its draft.
3. **One-time startup sweep** — module fn `purge_orphaned_staging_bpmn(bpmn_coll, sessions_coll)`
   ([`onboarding.py:110`](../../services/process-registry/app/services/onboarding.py#L110)), wired fail-soft into
   the lifespan ([`main.py:53-62`](../../services/process-registry/app/main.py#L53-L62)). It drops every `__onb__*`
   row whose session is **absent or already `completed`**, and **keeps in-progress drafts** (a session whose state is
   not `completed` is still using its draft). Idempotent; logs the purge count; a hiccup never blocks startup.

The `_STAGING_BPMN_PREFIX = "__onb__"` constant now backs both `_staging_pk` and the sweep's `$regex`.

**Tests.**
- New `tests/test_cb1_staging_bpmn_cleanup.py`:
  - `test_session_delete_purges_staging_bpmn` — create → attach_bpmn (stages draft) → delete → staging BPMN gone.
  - `test_startup_sweep_purges_orphans_but_keeps_in_progress` — seeds absent/committed/in-progress drafts + a real
    pack; asserts the sweep purges exactly the two orphans, keeps the in-progress draft and the real pack, and is
    idempotent on a second run.
- Extended `test_onboarding_fullset.py::test_e2e_message_pack_onboards_to_active` — after commit, asserts the
  `__onb__<session>` row is gone **and** the committed pack's own BPMN is intact (commit cleanup doesn't touch the
  real bundle).

**Acceptance met:** onboard→commit and onboard→delete both leave no `__onb__` row; the startup sweep clears
pre-existing orphans while sparing in-progress drafts; committed packs / runtime bundle load are unaffected
(full process-registry suite green).

---

## CB-2 — `capability_memo` after pack delete: verify + document (no code)

**Finding: orphaned-but-inert, accept by design. No instance GC, no ADR-061 change.**

Evidence:
- **`capability_memo` is per-instance, runtime-private (ADR-019).** In agent-runtime
  [`app/engine/executor/memo.py`](../../services/agent-runtime/app/engine/executor/memo.py): the store key is
  `(process_instance_id, element_id, inputs_hash, attempt, visit)` — the doc even carries `process_instance_id` —
  and `build_mongo_memo_store` opens `settings.MEMO_COLLECTION` (`capability_memo`) in the runtime's own DB. The
  docstring is explicit: "entries are scoped to a single `process_instance_id` so one instance never reads
  another's memo." The memo is **never keyed by `pack_key`/`pack_version`**.
- **ADR-061 pack deletion never touches runtime state.** `process-registry/app/services/deletion.py::delete_versions`
  deletes only registry rows: `process_packs`, `bpmn_documents`, owned `capabilities`/`artifact_schemas`, and
  `onboarding_sessions`. It has **zero** references to `capability_memo` / `MEMO_COLLECTION` / `process_instances`
  (verified by grep across process-registry). Architecturally it *can't* — the memo lives in agent-runtime's DB, a
  different service. The code even documents the intent: force-delete of an active pack warns "in-flight instances
  may strand if they resume against the removed bundle" — stranding in-flight instances (and their memos) is a
  deliberate ADR-061 choice.

So after a pack delete, any surviving memo rows belong to *instances*, not to the pack, and are never re-read except
by their own instance (which, if stranded, won't resume). They are orphaned-but-inert. This **confirms** the
expected disposition (no contradiction) — the memo is genuinely per-instance, not pack-scoped — so per the task
this is accepted by design with no code change and no instance GC.

---

## CB-3 — vestigial `sample_exceptions` / `sample-exception`

**Investigation → the fallback is NOT dead; it is a supported, live path.** Three live consumers of the sample
envelopes remain, so the preferred end-to-end *removal* would delete live behaviour. Per the task's explicit guard
("if a supported path genuinely still needs the fallback, do NOT remove — NEUTRALIZE naming only, across **both**
services"), I renamed instead.

Why the samples are still live (all in `process-registry`):

1. **`declare_trigger` is optional, not a state step.** Its docstring
   ([`onboarding.py:861`](../../services/process-registry/app/services/onboarding.py#L861)) says "Not a state step:
   an enrichment callable once the process is known." Onboarding therefore *supports* committing a pack with
   `trigger_artifact = None`. In that case `validate(..., trigger_schema=None)` →
   [`pack_validator.py:870`](../../services/process-registry/app/validation/pack_validator.py#L870)
   `field_types = infer_field_types(sample_envelopes)` — the samples are the **authoritative** triage field/type
   source, not a cosmetic default. Removing them would silently degrade triage validation for any no-trigger pack to
   the structural check only.
2. **Triage-picker default before a trigger is declared.**
   [`onboarding.py:333`/`:998`](../../services/process-registry/app/services/onboarding.py#L998)
   `s.trigger_fields or infer_field_types(self._samples)` — the samples seed the picker's typed field list during the
   wizard before/without a declared trigger.
3. **Informational triage smoke test for declared-trigger packs, too.**
   [`pack_validator.py:887-894`](../../services/process-registry/app/validation/pack_validator.py#L887-L894) still
   runs each triage rule against the conforming sample envelopes (an `info` MATCH/no-match log) on every
   same-domain onboarding — e.g. the wire packs against the wire sample.

**Rename applied** (`exception` → `trigger`), across **both** services because the seed dir is shared (the point the
reverted ADR-059 follow-up missed — it renamed only agent-runtime's dir and broke process-registry's reads):

Seed dirs (contents preserved; only the folder renamed):
- `agent-runtime/seed/wire-repair-standard/sample-exception/` → `…/sample-trigger/`
- `agent-runtime/seed/wire-repair-agentic/sample-exception/`  → `…/sample-trigger/`
- `agent-runtime/tests/fixtures/widget-qa/sample-exception/`  → `…/sample-trigger/`

agent-runtime code:
- `app/db/mongo.py` — `SAMPLE_EXCEPTIONS = "sample_exceptions"` → `SAMPLE_TRIGGERS = "sample_triggers"` (+ index).
- `app/dal/sample_repo.py` — `SampleExceptionRepository` → `SampleTriggerRepository` (+ docstring). Note: this
  collection is **seed-only / write-only** — nothing reads it at runtime — so renaming it is purely cosmetic
  vocabulary hygiene; it was kept (not dropped) to honour the guard's "neutralize across both services" and keep the
  seed loader symmetric.
- `app/seeding/load.py` — imports, `load_sample_exceptions` → `load_sample_triggers`, folder path, repo/collection
  wiring, and the seed-report label.
- `tests/test_seed_roundtrip.py` — reads `sample-trigger/`.

process-registry code (reads the shared seed folder only — no collection/repo of its own):
- `app/deps.py`, `app/routers/packs.py`, `app/seeding/onboard_seed.py` — folder path `sample-exception` →
  `sample-trigger`.
- `tests/conftest.py`, `tests/test_seed_pack_registry_gate.py` — folder path.

Docs (live guidance describing the current fallback, updated for correctness):
- `docs/methodology/amendia_mcp_backed_onboarding_runbook.md`, `…/amendia_process_onboarding_guide.md`,
  `…/worked-examples/restaurant/onboarding-guide.md` — `SEED_DIR/sample-exception` → `SEED_DIR/sample-trigger`.
- Historical records (ADR-049 / ADR-059, `_build-prompts`, `_build-reports`, the `known-issues/cleanup-backlog.md`
  source) intentionally **retain** the old term as a record of what changed.

**Acceptance met:** `rg "sample_exceptions|sample-exception|SAMPLE_EXCEPTIONS|load_sample_exceptions" backend`
returns nothing in code/live-docs (only historical ADR/build artifacts retain the term, by design); onboarding and
triage validation pass on a declared-trigger pack; both suites green.

---

## Verification

- **process-registry:** `uv run --extra dev pytest` → **366 passed** (includes the new CB-1 tests + the renamed
  seed-folder reads).
- **agent-runtime:** `uv run --extra dev pytest` → **343 passed, 4 skipped** (includes seed roundtrip + widget-qa
  fresh-domain neutrality reading the renamed `sample-trigger/` fixture).
- **CB-1 no-orphan check:** `test_session_delete_purges_staging_bpmn`, the extended commit e2e assertion, and
  `test_startup_sweep_purges_orphans_but_keeps_in_progress` all green.
- **CB-3 token sweep:** `rg 'sample_exceptions|sample-exception|SAMPLE_EXCEPTIONS|SampleExceptionRepository|load_sample_exceptions'`
  over the repo (excl. historical docs) → **none**.
- **Tree left dirty** for review (no git write commands run); directory renames done with plain `mv`, so git shows
  them as delete+add pairs.

## Files changed

CB-1: `process-registry/app/services/onboarding.py`, `process-registry/app/main.py`,
`process-registry/tests/test_cb1_staging_bpmn_cleanup.py` (new),
`process-registry/tests/test_onboarding_fullset.py`.

CB-2: none (verify + document only).

CB-3: `agent-runtime/app/db/mongo.py`, `agent-runtime/app/dal/sample_repo.py`, `agent-runtime/app/seeding/load.py`,
`agent-runtime/tests/test_seed_roundtrip.py`, three `agent-runtime` seed/fixture dir renames;
`process-registry/app/deps.py`, `process-registry/app/routers/packs.py`,
`process-registry/app/seeding/onboard_seed.py`, `process-registry/tests/conftest.py`,
`process-registry/tests/test_seed_pack_registry_gate.py`; three methodology docs.
