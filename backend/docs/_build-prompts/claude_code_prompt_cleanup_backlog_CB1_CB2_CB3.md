# Claude Code prompt — cleanup backlog CB-1, CB-2, CB-3

Work the three items in `backend/docs/known-issues/cleanup-backlog.md`. Two are real removals (CB-1, CB-3);
CB-2 is a **verify-and-document** item, not a code change (see its section — do not build a feature there).
Each is independent; keep them separable in the diff.

---

## CB-1 — Purge orphaned onboarding-draft BPMN (`__onb__<session>` keys)

**Confirmed cause.** Onboarding stores draft BPMN under a per-session staging key
`_staging_pk(s) = f"__onb__{s.session_id}"` (`onboarding.py:1191`), via `self.bpmn.upsert(self._staging_pk(s), …)`
(lines ~438/523/1126). Commit writes a second BPMN row under the **real** pack key but never removes the
staging row, and session delete (`OnboardingService.delete`, ~line 234) removes the session but not its staging
BPMN. So `bpmn_documents` accumulates `__onb__…` rows forever. (ADR-061 correctly deletes committed-pack BPMN —
that part is fine.)

**Read first:** `process-registry/app/services/onboarding.py` (`_staging_pk`, `delete`, `commit`/`_compose`
where the real-key upsert happens), `app/dal/bpmn_repo.py` (`delete`, `delete_pack`), `app/main.py` (startup).

**Fix:**
1. On **session delete**: after removing the session, delete its staging BPMN —
   `await self.bpmn.delete_pack(self._staging_pk(s))` (removes all versions under the staging key). Idempotent.
2. On **commit**: once the real-key BPMN is written, delete the staging BPMN for that session (same call), so a
   committed pack leaves no `__onb__` draft behind.
3. **One-time sweep** of pre-existing orphans: on startup (or a small idempotent maintenance routine), delete
   `bpmn_documents` rows whose `pack_key` starts with `__onb__` and whose `<session_id>` has no live
   `onboarding_sessions` row. Log the count purged.

**Acceptance:** onboard → commit (or delete the session) → no `__onb__…` row remains in `bpmn_documents` for that
session; the startup sweep clears existing orphans; committed packs and the runtime bundle load are unaffected.

## CB-2 — `capability_memo` after pack delete: VERIFY + DOCUMENT only (no code change)

**Do not write code for this unless the investigation contradicts the finding below.** Confirm and record the
disposition:

- Confirm `capability_memo` is the ADR-019 per-instance memoization store (`agent-runtime`, keyed by
  `process_instance_id`, runtime-private) — i.e. **instance** data, not registry/pack data.
- Confirm ADR-061 pack deletion intentionally does not touch runtime instances/checkpoints/memos (force-delete
  strands in-flight instances by design), so memos for a deleted pack's instances are orphaned-but-inert.
- **Disposition:** accept by design — retaining an instance's runtime/audit trail after its pack is deleted is
  reasonable (the instances *did* run). Purging them would be a separate cross-service "instance GC" feature
  (registry→runtime coordination, likely reacting to the `PackLifecycleEvent op=delete`) and would need its own
  ADR. Record this in the report; do NOT implement instance GC here.

**Acceptance:** the report states the verified facts and the accept-by-design disposition (or, if the
investigation shows `capability_memo` is genuinely pack-scoped/unused — it isn't expected to — say so and stop
for review rather than guessing).

## CB-3 — Remove the vestigial `sample_exceptions` / `sample-exception` fallback

**Confirmed state.** The deployment sample envelopes feed `self._samples` → `infer_field_types(self._samples)`,
used only as the **pre-trigger-declaration** `trigger_fields` default and as a triage-validation fallback when a
pack declares no trigger (`onboarding.py` ~310/431/975/1038/1134; `packs.py::_load_sample_envelopes`;
agent-runtime `seeding/load.py` `load_sample_exceptions`/`SampleExceptionRepository`/`SAMPLE_EXCEPTIONS`;
`db/mongo.py` `SAMPLE_EXCEPTIONS`). But **every** onboarded pack now declares a trigger — the seed reference
packs do (`wire-repair-agentic/manifest.json` has a `"trigger"`) and the copilot flow declares one (ADR-049/057)
— so the sample fallback is dead in practice, and it still carries the `exception` domain term ADR-059 evicted.

**Read first:** the `onboarding.py` sample sites above, `routers/packs.py::_load_sample_envelopes`,
`validation/pack_validator.py` (how `sample_envelopes` is used when no declared trigger),
`agent-runtime/app/seeding/load.py` + `db/mongo.py` (`SAMPLE_EXCEPTIONS`), and the `SEED_DIR/sample-exception`
dir (shared by both services).

**Fix (preferred — remove):** since all packs declare triggers, remove the sample-envelope fallback end to end:
delete the `sample_exceptions` collection + its index, the `sample-exception` seed dir/files, the reading code
(`SampleExceptionRepository`, `load_sample_exceptions`, `SAMPLE_EXCEPTIONS`, `_load_sample_envelopes`), and the
`sample_envelopes`/`self._samples` plumbing (default to `[]`/`None`). With no samples, the pre-declaration
`trigger_fields` is simply empty (free-text) until the operator/copilot declares the trigger — a harmless UX
default — and triage validation uses the declared trigger (ADR-049) or degrades to structural-only, as it already
does when samples are absent.

**Guard:** if the investigation shows a *supported* onboarding path that genuinely still needs the sample
fallback (a pack that never declares a trigger), do NOT remove — instead **neutralize the naming only**
(`sample_exceptions`→`sample_triggers`, `sample-exception`→`sample-trigger`) across BOTH services (the seed dir is
shared — this is what the reverted ADR-059 follow-up got wrong), and report that you took the rename path and why.

**Acceptance:** `rg -n "sample_exceptions|sample-exception|SAMPLE_EXCEPTIONS|load_sample_exceptions" backend`
returns nothing (removal path) or only neutral renamed identifiers (rename path); onboarding a pack (seed +
copilot) still works; triage validation still passes on a declared-trigger pack; `pytest` green for
process-registry + agent-runtime.

---

## Do not
- Do not build instance GC (CB-2) or change ADR-061 delete.
- Do not touch ADR-059/060/061/062 behaviour, HITL gating, or the type-compat guard.
- No git writes — leave the tree dirty; the operator owns commits.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_cleanup_backlog_CB1_CB2_CB3_report.md` (uncommitted):
per item (CB-1 / CB-2 / CB-3) — outcome one-liner, what changed (files) or (CB-2) the verified disposition,
and verification (commands + results: the `rg` checks, a "no `__onb__` orphan remains" check, `pytest`,
onboarding still works). Note explicitly for each whether it is **done / accepted-by-design / rename-fallback**
so the backlog entries can be struck through. Keep it to a screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. Prefer the fix at the right layer over a shim. Stay
inside the Amendia repo and the scope above.
