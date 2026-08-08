# Cleanup backlog — small DB/residue items

A living list of small, low-urgency issues (stray collections, orphaned rows, residue from past ADRs) found
during review. Not architectural decisions — each is a bounded cleanup. Add new items at the bottom with the
next `CB-##`; keep the finding honest (verified vs suspected) so the fix scope is clear.

Status legend: `open` · `investigating` · `fix-prompted` · `done` · `wontfix`.

---

## CB-1 — Orphaned onboarding-draft BPMN in `bpmn_documents` (`__onb__…` keys)

- **Area:** process-registry · `bpmn_documents`
- **Observed (Compass):** rows keyed `pack_key = "__onb__onb-<session>"` (e.g. `__onb__onb-a86663148dbe`,
  versions 1.0.0 / 1.1.0) remain after packs come and go.
- **Finding:** ADR-061 delete **does** remove a committed pack's BPMN — `deletion.py` calls
  `bpmn_repo.delete(pack_key, version)` for the real pack key. These leftovers are a **separate** issue:
  onboarding stores the draft BPMN under a temporary `__onb__<session>` pack key, and nothing garbage-collects
  it — not commit, not `DELETE /onboarding/{session}` (which removes the session row but not its draft BPMN),
  not pack delete (different key). So draft BPMN accumulates per onboarding session.
- **Severity:** low (inert scratch; never loaded by the runtime, which reads by real pack key).
- **Suggested fix:** purge the session's `__onb__<session>` BPMN when the onboarding session is deleted (and/or
  when a commit re-keys it to the real pack), or a periodic sweep of `__onb__*` rows with no live session.

## CB-2 — `capability_memo` rows for a deleted pack's instances (NOT a pack-delete gap)

- **Area:** agent-runtime · `capability_memo`
- **Observed:** rows keyed by `process_instance_id` (e.g. `pi-036f3d1ebab54936::Enrich::…`) persist after a pack
  is deleted.
- **Finding:** the collection **is** used — it is ADR-019 per-instance capability memoization (a runtime-private,
  crash-durable store scoped by `process_instance_id`, so one instance never reads another's memo). It is
  **runtime instance** data, not registry/pack data. ADR-061 pack deletion deliberately does **not** touch
  runtime instances, checkpoints, or memos (force-delete strands in-flight instances by design). So memos for a
  deleted pack's instances are orphaned-but-inert — this is expected, not a delete-cascade bug.
- **Severity:** low (inert; correct by ADR-061's scope).
- **Suggested fix (future, optional, cross-service):** a runtime-side "instance GC" that purges an instance's
  `process_instances` + `lg_checkpoints` + `lg_checkpoint_writes` + `capability_memo` + `hitl_tasks` when its
  pack is deleted. This is a separate feature (registry→runtime coordination), intentionally out of ADR-061.

## CB-3 — `sample_exceptions` collection is exception-domain residue

- **Area:** agent-runtime (`seeding/load.py`, `SAMPLE_EXCEPTIONS`, `SampleExceptionRepository`) + process-registry
  (`packs.py::_load_sample_envelopes` reads `SEED_DIR/sample-exception`)
- **Finding:** still seeded and still read as the ADR-049 **trigger-field-inference fallback** (sample envelopes
  used only when a pack declares *no* trigger). Copilot-onboarded packs declare their trigger (ADR-049/057), so
  this fallback path is effectively dead for the current onboarding flow. The collection/dir also still carry the
  `exception` domain term the ADR-059 cleanup evicted elsewhere (the ADR-059 follow-up Task-2 rename was reverted
  because the seed tree is shared).
- **Severity:** low (vestigial; harmless but a domain-neutrality leak + dead-ish path).
- **Suggested fix:** confirm no active read path for copilot-onboarded packs; then either drop the
  collection + `sample-exception` seed dir, or (minimum) rename off the `exception` term to a neutral
  `sample-trigger` / `sample_triggers` (the reverted ADR-059 follow-up), being careful the seed dir is shared by
  both process-registry and agent-runtime.

---

*Started 2026-08-08 during ADR-061 review. Owner: Sandeep.*
