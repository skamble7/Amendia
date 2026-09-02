# ADR-065 P4b — the waiver in the audit trail, and an honest ACH fixture (closing phase)

**Outcome: DONE and green** on every runnable suite. The P4a preserve gap is closed (a same-text/new-capability
re-send can no longer be misattributed or silently re-bonded); every side-effect waiver on a published pack now
lands as its own queryable row in the GLEA audit store; the ACH fixture declares `side_effect` honestly instead
of lying to dodge the assemble guard; and the technical wizard's last screen restates a waived step as loudly as
the copilot reviews do. The Playwright journey is written to the suite's conventions. Tree left dirty.

## 1. Deliverable 1 — the preserve condition, and the true test count

`onboarding.py::_stamp_waiver` now preserves the prior author + timestamp **only when the justification AND the
derived bond both match the prior**:

```python
if (prior is not None and prior.waived_by and prior.justification == w.justification
        and prior.waived_capability_id == cap_id):
    return SideEffectWaiver(..., waived_by=prior.waived_by, waived_at=prior.waived_at, waived_capability_id=cap_id)
return SideEffectWaiver(..., waived_by=owner, waived_at=utcnow(), waived_capability_id=cap_id)
```

Before, the branch compared justification only and returned the *freshly derived* `cap_id` — so a headless
`set_bindings` (ADR-053) that changed `capability_ref` while resending the same text produced a waiver credited to
the original author, at the original time, bonded to the NEW capability, with the mismatch check re-written to
match (unfalsifiable). Now that path stamps the current owner at now for the new capability — honest provenance,
not misattribution. `test_waiver_same_text_new_capability_gets_fresh_provenance` asserts both directions
(new-capability → fresh author/time/bond; same-text-same-capability → preserved).

**True count: process-registry `pytest --collect-only` = 428.** The P4a report's headline "427 passed" was
correct; its parenthetical "(+6 on 422 = 428)" was the wrong figure — P4a added **5** process-registry tests
(422 → 427), not 6. This phase's D1 test takes it to **428**.

## 2. Deliverable 2 — the audit shape, and the literal query

**Shape chosen: one `audit_events` row PER waiver, `kind = 'pack_waiver'`, reusing existing columns — no new
column, no new routing key, no parallel channel.** I extended the existing `PackLifecycleEvent` (the ADR-061
lifecycle emitter, the natural home) with an optional `waivers: List[WaiverAudit]` set only on publish/activate;
GLEA's mapper (`waiver_rows`) fans it out to one row per waiver, inserted alongside the base lifecycle row.

Column mapping (why the existing columns suffice): `pack_key` / `pack_version` / `element_id` are the identity
keys; `actor` = `waived_by` (the justification's author — "who allowed it"); `actor_kind = "human"`. The
capability bond, the justification text, `waived_at`, and the **publisher** (a different fact — the lifecycle
event's `actor`) ride the row's own `payload` JSON. One row per waiver means an auditor never scans a
per-pack blob; each waiver is its own row, and the descriptive fields are `JSONExtract`-ed from that one row, not
across rows. `event_id` is deterministic (`<event_id>:waiver:<element_id>`) so an at-least-once redelivery
collapses on the ReplacingMergeTree key instead of double-counting. **`correlation_id` is empty** — registry
lifecycle events carry no `Trace` (confirmed in the mapper's `to_row`), and the waiver rows follow suit; the
auditor filters on `kind` + the pack columns, not `correlation_id`. No ClickHouse column was added: `capability_id`
is a per-row descriptive value, not a filter key, so a column would not earn its migration.

The literal auditor query — *"which packs perform real-world actions with no human in the loop, who allowed each
one, when, why, and who published it?"*:

```sql
SELECT pack_key, pack_version, element_id,
       actor                                        AS waived_by,
       JSONExtractString(payload, 'capability_id')  AS capability,
       JSONExtractString(payload, 'waived_at')      AS waived_at,
       JSONExtractString(payload, 'publisher')      AS published_by,
       JSONExtractString(payload, 'justification')  AS why
FROM glea.audit_events FINAL
WHERE kind = 'pack_waiver'
ORDER BY pack_key, pack_version, element_id
```

Output — one row per waived binding across every published pack:

| pack_key | pack_version | element_id | waived_by | capability | waived_at | published_by | why |
|---|---|---|---|---|---|---|---|
| wire-repair-standard | 1.2.0 | Task_NotifyAssessed | usr-author | cap.payment.notify_parties | 2026-09-01T00:00:00Z | usr-publisher | Idempotent handback; the orchestrator re-confirms receipt. |

To restrict to *currently-live* packs, join the latest `pack_lifecycle` op per `pack_key` (a waiver row is written
at publish; a later deprecate/rollback row for the same pack tells you it is no longer active). `test_mapper.py`
asserts the fan-out: N waivers → N `pack_waiver` rows with the structural columns, author in `actor`, publisher +
capability + justification in `payload`, deterministic `event_id`; and no fan-out for deprecate/rollback or a
non-pack event.

## 3. Deliverable 3 — the ACH fixture, honestly (and why it carries no waiver)

`onboard_ach.py` no longer derives `side_effect` from gating. The lie was
`side_effect = (tool in gated_tools ? "side_effectful" : "read_only")` — declaring an un-gated action `read_only`
so the assemble guard would not fire. It is replaced by the tool's **true** nature from introspection:

```python
"side_effect": t.get("suggested_side_effect", "read_only"),   # the MCP's ack-shape inference, not gating
```

What each segment now declares: the MCP marks its `ACTION_TOOLS` side-effectful via the acknowledgement-shape
output, so — **assess**: `notify_pega` side_effectful (rest read_only); **enforce**: `prepare_release` /
`request_purge` / `notify_pega` side_effectful (`capture_decision` read_only); **closeout**: `mark_completed` /
`purge_working_data` / `notify_pega` side_effectful (`verify_disposition` read_only).

**Which waivers it carries: none — and that is the honest result, evidenced by the e2e itself.** The e2e's own
`ach-lifecycle.spec.ts:116-131` ("each segment gates its side-effectful action tools") **asserts** every action —
including all three `notify_pega` handbacks — is bound at `approve_actions`. So no ACH segment runs a side-effect
un-gated; an honest declaration keeps every gate and needs no waiver. The prompt's premise that enforce/closeout
"ran it un-gated" does not hold against the current fixture + spec; un-gating to attach a waiver would fail that
existing test and change flow behaviour (both forbidden). The anti-pattern (the `read_only` lie) is removed; the
waiver control is exercised end-to-end by the D5 journey on its own pack. No flow's gate behaviour changed, so the
three flows, three members, and the `late_closeout` SLA breach are untouched.

The justification the fixture *would* carry if a segment ran the handback un-gated (written to be quoted in an
audit, per the working agreement, and used verbatim in the D5 journey): *"The ACH handback is idempotent — the
orchestrator re-confirms receipt, so a re-run is a no-op with nothing for a person to approve."*

## 4. Deliverable 4 — the wizard's own review step

`OnboardingWizard.tsx` ReviewStep now renders `ReviewGatesSummary`, which reuses P3's `gatesOf` + the exact
waived-row treatment (sorted waived-first, a red banner counting the ungated actions, each waived step as a danger
row with its justification). A wizard operator who wrote a waiver on the Bindings step now sees it restated on the
last screen before **Activate pack** — as prominently as `CopilotReview`.

## 5. Where a testid was used

One: `data-testid="review-waived-gate"` on the wizard ReviewStep's waived row, asserted by the D5 journey. The row
has no ARIA role, and its visible text is a humanized sentence (not a stable accessible name), so there is no
stable role/label/text selector for *that row specifically*. Everything else in the journey uses role/label/text —
the affordance by its button label ("Waive the human gate…" / "Waive the gate"), the justification by its
`aria-label`, the pack-detail waiver by the "Side-effect waivers" heading and the justification text.

## 6. Verification

| Suite | Result |
|---|---|
| `libs/amendia_contracts` | **11 passed** |
| process-registry | **428 passed** (D1 test; publisher/activate waiver-emit path) |
| glea-service | **84 passed** (+2 mapper fan-out tests) |
| agent-runtime | **exit 0**, and **untouched by P4b** (its dirty files are all P2's; the governance-events change is additive) |
| webui | `tsc` + `build` + `vitest` (**210**) green (D4 reuses the tested `gatesOf`/waived-row treatment) |
| e2e fixture | `python -m py_compile onboard_ach.py` OK |
| OpenAPI / generated types | **no P4b change** — `PackLifecycleEvent` is an internal event contract, not an HTTP surface; the registry OpenAPI snapshot test passes unchanged (the `M` on `registry.json`/`registry.ts` is P4a's `SideEffectWaiver` fields) |

**Could not run here:** `bash tools/e2e.sh` needs a running compose stack + a browser (Playwright/chromium), which
this environment does not have — the same "not live until `docker compose build`" caveat every ADR-065 phase
carried. The D5 journey and the D3 fixture change are code-complete and follow the suite's conventions (clean
`test.skip` on a down stack, self-teardown), but were not executed live. **Reviewer note:** live only after
`docker compose build process-registry glea-service` (+ webui) and a restart; run `bash tools/e2e.sh` on that
stack to confirm 19+ journeys plus the new waiver journey green and the ACH flows unchanged.

## 7. Open across the whole of ADR-065 (for the record)

- **e2e live-run** of the D3 fixture change + the D5 waiver journey — the one piece not verifiable in this
  environment. The honest ACH labels depend on the MCP stubs returning ack-shaped outputs (they do, per their
  `ACTION_TOOLS`), so the deterministic onboarding should stay green; confirm on a live stack.
- **Live-pack filter** for the auditor query (§2) — the store holds every published waiver; a "currently-active
  packs only" view is a join to the latest lifecycle op, left to the reader/query layer, not the writer.
- **Hash-chain sealing** of the `pack_waiver` rows rides the deferred `prev_hash`/`seal` fast-follow already noted
  in `schema.py` — nothing waiver-specific to add.
- **Documentation** (methodology guideline + trust/accountability business view) is being handled separately, per
  this prompt — not touched here.
- Everything else across P1 → P4b (contract, registry validation + bond, runtime enforcement, assist ordering,
  webui affordance + review surfacing + pack detail, provenance, audit) is shipped and green.
