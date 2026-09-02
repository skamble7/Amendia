# Claude Code prompt — ADR-065 P4b: the waiver in the audit trail, and an honest ACH fixture (closing phase)

Closing phase of **ADR-065**. P1, the rebind guard, P2, the assist-ordering correction, P3 and P4a are all
shipped and reviewed. This phase fixes one gap found reviewing P4a, puts the waiver into the audit store, and
migrates the ACH fixture off the mislabeling workaround that motivated the whole ADR. Read the ADR and
`backend/docs/_build-reports/claude_code_prompt_ADR065_phase4a_waiver_provenance_and_bond_report.md` §7 (the
fully-provenanced manifest shape) first.

Documentation is **not** in this prompt — the methodology guideline and the trust/accountability business view
are being updated separately.

## Deliverable 1 — the P4a preserve gap (do this first; D2 depends on it)

`services/onboarding.py::_stamp_waiver` (:860-875) computes `cap_id = self._bond_cap_ref(b)` **outside** the
preserve branch, then the preserve path returns `waived_by=prior.waived_by, waived_at=prior.waived_at,
waived_capability_id=cap_id` — the *freshly derived* bond. The preserve condition (:871) compares the
**justification only**, never the capability.

So a direct `set_bindings` that changes `capability_ref` while resending the same justification produces a waiver
that authorises the **new** capability, is credited to the **original** author at the **original** timestamp, and
validates **clean** — the bond was just re-derived to match, so `side_effect_waiver_capability_mismatch` can
never fire on it. The wizard (P3 D2) and the copilot (`_waiver_drop_reason`) both drop a waiver on a capability
change; `_stamp_waiver` — the server-side chokepoint P4a existed to harden — does not. ADR-053 makes headless API
operation first-class, so this is a real path.

**Fix:** preserve author + timestamp only when the justification **and** the derived bond both match the prior;
otherwise stamp fresh. Not a rejection — an owner re-sending the same text for a new capability may be
deliberate, and stamping *them* at *now* is honest provenance. The defect is the misattribution and the bond that
becomes unfalsifiable because the server wrote it to match.

This lands before D2 because the audit payload records `waived_by`: a misattributed author is least recoverable
once it is in a 7-year store.

**Also:** the P4a report gives process-registry as 427 (+6 on 422 = 428). Run `pytest --collect-only -q | tail -1`
and state the true count and which figure was wrong.

## Deliverable 2 — the waiver in the audit trail

**The requirement, not the implementation:** an auditor must be able to answer *"which live packs perform
real-world actions with no human in the loop, who allowed each one, when, and why?"* **from the audit store
alone** — without scanning JSON blobs across every pack-lifecycle row.

Emit the waiver set to GLEA when a pack is published/activated, carrying per waiver: `element_id`, the bonded
capability id, the justification, `waived_by`, `waived_at` — plus the **publisher** of the pack, which is a
different fact from the justification's author and both are worth having.

Find the existing pack-lifecycle event first (ADR-061 emits `PackLifecycleOp.DELETE` to GLEA *before* row
removal — the same emitter is the natural home) and extend it rather than inventing a parallel channel. Then work
out the shape that satisfies the query requirement: `audit_events` is a fixed-column ClickHouse table
(`kind`, `element_id`, `pack_key`, `pack_version`, `actor`, `payload`, …), so **one row per waiver** is likely to
serve the auditor far better than one blob per pack — but confirm against the real schema and sorting key,
including what existing pack-lifecycle events put in `correlation_id`, and **state your choice and why in the
report**. `glea-service`'s consumer/mapper must recognise whatever you emit.

Do not add a ClickHouse column without saying why the existing ones do not suffice.

## Deliverable 3 — migrate the ACH fixture off mislabeling

`e2e/fixtures/onboarding/onboard_ach.py:171-176` declares `notify_pega` `read_only` in the segments where the
pack does not gate it, *specifically so the assemble guard does not fire*. That workaround is the evidence that
opened ADR-065; it should not outlive it.

Declare each tool's `side_effect` **honestly**, and where a segment genuinely runs it un-gated, attach a real
`side_effect_waiver` with a justification that would survive review — the ACH handback is idempotent and the
orchestrator re-confirms receipt, so the honest justification is easy to write and worth writing well: this
fixture is what future readers will copy.

**Preserve each segment's current gate behaviour exactly** — Segment A keeps its `approve_actions` gate on
`Task_NotifyAssessed`; segments that ran it un-gated keep running it un-gated, now via a waiver instead of a lie.
The deterministic gate (`bash tools/e2e.sh`, 19 passed) must stay green, and `assertThreeMembersClosed` must
still hold for all three flows.

## Deliverable 4 — the wizard's own review step

P3 surfaced waived steps in `CopilotReview` and `CopilotSteppedReview`, but the technical wizard's `ReviewStep`
(`OnboardingWizard.tsx:2253`) has no gates summary — so a wizard operator writes a waiver on the Bindings step
and then passes the **last screen before publishing** without the ungated action being restated. Close it, reusing
P3's `gatesOf` + the waived-row treatment rather than a second rendering.

## Deliverable 5 — the Playwright journey

Add the journey P3's report §8 scoped: as **priya**, drive a side-effectful capability to a waiver through the
UI, assert the affordance refuses a short justification, assert the waived step appears in the review summary,
publish, and assert the waiver renders on the pack detail page.

Prefer role / label / text selectors over the `data-testid` hooks P3 added — the existing suite is deliberately
testid-free and a journey that reads like a user's path stays truer as the UI changes. Use a testid only where no
stable accessible selector exists, and say where in the report.

It belongs in the deterministic gate (`tools/e2e.sh`), not the copilot command, and must tear down after itself
like the rest of that suite.

## Do not

- Do not change the waiver contract, the waivable/non-waivable split, the runtime checks, or any P1–P4a finding
  code beyond Deliverable 1's preserve condition.
- Do not weaken the ACH fixture's coverage to make Deliverable 3 easier — the three flows, three members, and the
  `late_closeout` SLA breach must all still hold.
- Do not add a way for the LLM to create or suggest a waiver.
- Do not update the methodology guideline or the business-view doc — those are being handled separately.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- Deliverable 1: same justification + changed capability via `set_bindings` → **fresh** author and timestamp, not
  the prior's. Same justification + same capability → author and timestamp preserved. Both asserted.
- An auditor query against the audit store returns every waived binding across live packs with its capability,
  justification, author, timestamp and publisher — demonstrate the actual query in the report.
- `bash tools/e2e.sh` green (19+ passing, plus the new journey), with the ACH fixture declaring `side_effect`
  honestly and carrying real waivers; no flow's behaviour changed.
- The wizard's ReviewStep shows waived steps as prominently as the copilot reviews do.
- `pytest` green for process-registry and glea-service; agent-runtime untouched; webui `tsc`/`build`/`vitest`
  green. Re-dump OpenAPI + regenerate types if the emitted event changes any API surface (say so if it does not).
- **Reviewer note:** live only after `docker compose build process-registry glea-service` (+ webui if D4 ships a
  UI change), and a restart.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR065_phase4b_waiver_audit_and_fixtures_report.md`
(uncommitted): (1) outcome one-liner; (2) Deliverable 1's new preserve condition, and the true test count;
(3) **the audit shape you chose, why, and the literal auditor query with its output**; (4) the ACH fixture diff
in words — what each segment now declares and which waivers it carries, with the justification text quoted;
(5) where you had to use a testid and why; (6) verification — commands and results, including the full e2e run;
(7) anything left open across the whole of ADR-065, for the record.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Registry + glea-service + webui + the ACH fixture +
e2e. Deliverable 1 first and independently testable. The ACH fixture is the part future readers will copy —
write its justifications as if they will be quoted back in an audit, because that is exactly what this feature is
for.
