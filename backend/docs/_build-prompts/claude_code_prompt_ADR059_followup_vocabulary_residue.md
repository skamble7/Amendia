# Claude Code prompt — ADR-059 follow-up: vocabulary residue (cosmetic)

Small, low-risk cleanup completing ADR-059
(`backend/docs/adr/ADR-059-domain-neutrality-cleanup-trigger-vocabulary-and-store-consolidation.md`).
The functional rename is done and the wire e2e path runs green; these are leftover "exception" strings/identifiers
in **platform** code that the sweep missed. No wire-contract, routing-key, collection, or API changes.

## Read first

- `backend/services/process-registry/app/models/registry.py` (around line 75 — the resolve no-match model).
- `backend/services/process-registry/app/routers/resolve.py` (confirms how that default `detail` reaches the 404).
- `backend/services/agent-runtime/app/seeding/load.py` (lines ~104, 157, 159).
- `backend/services/agent-runtime/app/db/mongo.py` (line ~75, `SAMPLE_EXCEPTIONS`).
- `backend/services/agent-runtime/tests/test_seed_roundtrip.py` (line ~51, the seed path).
- Confirm scope: re-read the "DO NOT rename" section of ADR-059 before touching seed **data**.

## Task 1 (required) — neutralize the registry no-match message

`process-registry/app/models/registry.py:75` defaults to `detail: str = "no active pack matched the exception"`.
The ingestor echoes this verbatim into its `no_process` log, so the word "exception" still surfaces at runtime.
Change the default to `"no active pack matched the trigger"`. Update any test asserting the old string. This is the
string a business user could see for a genuinely-unmatched trigger, so it must read domain-neutrally.

## Task 2 (optional — do it unless it fights the tests) — neutralize the seed-helper identifiers

The agent-runtime seed helper still uses "exception" for its generic identifiers, even though its role is
"load sample **triggers** for onboarding field inference" (ADR-049 fallback). Neutralize the **identifiers**, but
**keep the wire sample DATA domain-named** (it is reference-domain data per ADR-059):

- `seeding/load.py`: `load_sample_exceptions` → `load_sample_triggers`; its call site (~157); the log label
  `f"sample-exception {sample['exception_id']}"` → `f"sample-trigger {sample['exception_id']}"` — note
  `sample['exception_id']` reads a **wire sample field** and stays as-is (domain data).
- `db/mongo.py`: `SAMPLE_EXCEPTIONS = "sample_exceptions"` → `SAMPLE_TRIGGERS = "sample_triggers"`; update references.
  (Seed-only collection, recreated on seed — safe on clean-slate.)
- Seed directory `.../seed/sample-exception/` → `.../seed/sample-trigger/`, keeping the wire sample **file**
  (`wire-exception-ac01.json`) and its contents domain-named. Update the path in `test_seed_roundtrip.py`.
- If a `SEED_REFERENCE_PACK`/seed path env or compose var points at `sample-exception`, update it to match.

If any of this collides with fixtures beyond the one test above, stop at Task 1 and note it in the report rather
than chasing a wide fixture rename — the value here is cosmetic.

## DO NOT

- Touch wire/dine payload **contents**, schema-version ids (`pin.payments.wire_exception/1.0`), seed pack data,
  domain MCP servers, or the `wire-exception-ac01.json` file contents.
- Rename `logger.exception(...)` calls anywhere — that is the Python logging API, not domain vocabulary.
- Change any routing key, queue, collection-in-use (`trigger_messages`, `ingestions`), or HTTP path.

## Acceptance

- `rg -n 'the exception' backend/services` returns nothing (or only domain-data strings).
- Backend `pytest` green for `process-registry` and `agent-runtime` (seed round-trip included).
- No functional diff: routing keys, queues, `trigger_messages`, and all HTTP paths unchanged.

## Final step — implementation report (required)

After the work and tests, write a markdown report to
`backend/docs/_build-reports/claude_code_prompt_ADR059_followup_vocabulary_residue_report.md` (create the
`_build-reports/` dir if absent). Do **not** commit it. Cover, concisely:

1. **Outcome** — one line: done / partial / blocked.
2. **Changes by file** — each file touched and what changed (Task 1, and whether Task 2 was done or skipped + why).
3. **Decisions / deviations** — anything you did differently from this prompt, and why.
4. **Left as-is** — domain data or fixtures you deliberately did not rename.
5. **Verification** — exact commands run (`rg`, `pytest …`) and their results (pass/fail counts).
6. **Follow-ups / questions for the reviewer** — anything Claude should look at via the bridge.

Keep it tight (a screen or two). This report is what Claude reviews — it is the deliverable's cover sheet, not a
narration of every edit.

## Working agreement

You do not run git (no add/commit/push/branch) — leave the tree dirty; Sandeep reviews and owns commits. Prefer a
real fix over a shim. Stay inside the Amendia repo and the scope above.
