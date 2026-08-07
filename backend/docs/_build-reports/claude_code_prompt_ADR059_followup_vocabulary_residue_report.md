# ADR-059 follow-up — vocabulary residue (cosmetic): implementation report

## 1. Outcome

**Partial (by design).** Task 1 (required) is **done and verified green**. Task 2 (optional) was
**deliberately skipped and fully reverted** — it collides with the process-registry service beyond the
one in-scope test, exactly the "stop at Task 1" guardrail in the prompt.

## 2. Changes by file

**Task 1 — registry no-match message (done):**
- `backend/services/process-registry/app/models/registry.py` — `NoMatchResponse.detail` default
  `"no active pack matched the exception"` → `"no active pack matched the trigger"`. This is the string the
  ingestor echoes verbatim into its `no_process` log, so it now reads domain-neutrally at runtime.
- `webui/openapi/registry.json` — regenerated via `python scripts/dump_openapi.py`. The one-line delta is
  **not** from Task 1 (the /resolve 404 uses a bare `JSONResponse`, so `NoMatchResponse.detail` never enters
  the OpenAPI). It is stale drift from the earlier ADR-059 Phase-1 edit to the `MessageExecutor` contract
  docstring (`amendia_contracts/process_pack.py`: anchor `exception_id → trigger_id`), which flows into the
  registry schema description. Regenerating it is in-scope for ADR-059 and unblocks
  `test_openapi_snapshot.py`. (The matching `gen/registry.ts` comment was already updated in Phase 2; the
  operator's Phase-3 `npm run gen:api` will confirm gen/ ↔ snapshot parity.)

**Task 2 — seed-helper identifiers (attempted, then fully reverted; net zero change):**
Edited then reverted: `app/dal/sample_repo.py` (`SampleExceptionRepository`), `app/db/mongo.py`
(`SAMPLE_EXCEPTIONS`), `app/seeding/load.py` (`load_sample_exceptions`, imports, folder path, log label),
`tests/test_seed_roundtrip.py` (path + test fn), and the seed dirs
`seed/wire-repair-{standard,agentic}/sample-exception/`. All restored to their original names/paths.

## 3. Decisions / deviations

- **Reverted Task 2** after discovering the seed tree is **shared**, not agent-runtime-local:
  `backend/services/process-registry/Dockerfile` does `COPY backend/services/agent-runtime/seed` and sets
  `REGISTRY_SEED_DIR=…/agent-runtime/seed/wire-repair-standard`; its test conftest reads the same path.
  process-registry independently references the `sample-exception` folder in **five** places
  (`app/deps.py`, `app/seeding/onboard_seed.py`, `app/routers/packs.py`, `tests/conftest.py`,
  `tests/test_seed_pack_registry_gate.py`). Renaming the folder to `sample-trigger` would break
  process-registry's sample-envelope onboarding and those tests — a cross-service fixture rename well beyond
  the prompt's scope. Per the explicit guardrail ("If any of this collides with fixtures beyond the one test
  above, stop at Task 1 and note it… the value here is cosmetic"), I stopped and reverted rather than
  chasing it or shipping a half-rename that breaks the stack.
- **Regenerated the OpenAPI snapshot** rather than leaving `test_openapi_snapshot.py` red. The drift is a
  genuine ADR-059 consequence, and the snapshot dump is a local, backend-free script.

## 4. Left as-is (intentional)

- All seed **pack data** and the `wire-exception-ac01.json` sample file + contents (reference-domain, ADR-059
  DO-NOT set).
- The seed folder name `sample-exception`, collection `sample_exceptions`, `SampleExceptionRepository`,
  `load_sample_exceptions`, `SAMPLE_EXCEPTIONS` — reverted; see Task 2 rationale above.
- Domain-data `the exception` strings surfaced by the acceptance grep (all permitted — "only domain-data
  strings"):
  - `agent-runtime/tests/test_error_boundary.py:92` — comment about the DOMAIN wire-envelope field
    `exception_id` that `apply_repair`'s closed inputSchema receives.
  - `seed/wire-repair-{standard,agentic}/artifact-schemas/art.payment.resolution_record.json` and
    `capabilities/cap.payment.draft_return.json` — seed-pack descriptions narrating the wire-payments domain.
- `logger.exception(...)` calls (Python logging API) — untouched, per DO-NOT.
- No routing key, queue, in-use collection (`trigger_messages`, `ingestions`), or HTTP path changed.

## 5. Verification

- `rg -n 'the exception' backend/services` → only the 5 domain-data strings listed in §4 (acceptance:
  "nothing, or only domain-data strings" — met).
- `rg -n 'SAMPLE_TRIGGERS|SampleTriggerRepository|load_sample_triggers|sample-trigger|sample_triggers'
  backend/services/agent-runtime` → **none** (Task 2 cleanly reverted).
- `cd backend/services/process-registry && uv run --extra dev pytest` → **337 passed**.
- `cd backend/services/agent-runtime && uv run --extra dev pytest` → **342 passed, 4 skipped**
  (seed round-trip included).
- No functional diff: routing keys, queues, `trigger_messages`/`ingestions`, and all HTTP paths unchanged.

## 6. Follow-ups / questions for the reviewer

- **Task 2, if wanted, is a cross-service change** — do it deliberately across agent-runtime **and**
  process-registry together (folder + the 5 process-registry references + collection const + both packs'
  `sample-exception` dirs), on a clean-slate `down -v` since the seed-only `sample_exceptions` collection is
  recreated on seed. Recommendation: leave it. The identifiers are internal/seed-only, the folder holds
  reference-domain wire data (`wire-exception-ac01.json`), and the payoff is purely cosmetic while the blast
  radius spans two services' onboarding paths and tests.
- `webui/openapi/registry.json` is now regenerated locally; the operator still runs `npm run gen:api` +
  `gen:api:check` against the live stack in Phase 3 — this snapshot change should make that a no-op for the
  `MessageExecutor` description.
