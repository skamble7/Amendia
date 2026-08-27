# Claude Code prompt — fix the flaky `dag-sla-editor` forward-only assertion (state-dependent)

`e2e/tests/dag-sla-editor.spec.ts:48` ("editing the real ACH definition shows the forward-only warning") is
**flaky** — green one run, red the next. Not a product bug; the test asserts a **conditional** UI element
unconditionally.

**Root cause:** in `webui/src/features/cohorts/CohortDefinitionPage.tsx` the forward-only warning renders **only when
the definition has observed instances** — `{instances.length > 0 && ( … Graph / SLA edits are forward-only … )}`
(≈ lines 264–267; the membership one at ≈288 is the same). It is *correctly absent* at zero instances. Whether
`ach_exposure_cohort` has any observed instances when this test runs depends on **leftover ClickHouse cohort data
from prior runs** (ClickHouse isn't reset by the identity/Mongo seed), because `hitl-arc` — which fires this run's
ACH case — runs *after* `dag-sla-editor` in file order. Clean ClickHouse → zero instances → no warning → red.

## Fix (make it deterministic, keep the coverage) — `dag-sla-editor.spec.ts` (test 2, line ~48)
Split what's unconditional from what's instance-dependent:
- **Always assert the editor is live** (unconditional): after `startEdit()`, assert the DAG/SLA editor rendered —
  the "Expectation graph & SLAs" card / the `Add edge` button — and the Cancel→no-mutation flow. This is the core
  of the test and must not depend on instances.
- **Assert the forward-only warning deterministically** by first **guaranteeing ≥1 observed instance** on the ACH
  definition, instead of relying on leftover state. Read the **"Instances" KPI** (`<Kpi label="Instances">`) on the
  definition detail; if it's `0`, **fire one ACH case** via the existing driver (the same `pega_stub`/driver the
  `hitl-arc`/`live-sse` journeys use) and **poll the definition until the Instances KPI ≥ 1** (GLEA/ClickHouse
  ingest is async — `expect.poll`, no fixed sleep). Then enter edit and assert the **forward-only** text is visible.
  This exercises the warning every run regardless of prior ClickHouse state.
- **Acceptable lighter fallback** (if firing here is undesirable): make the warning assertion **conditional on the
  KPI** — assert the forward-only text **iff** Instances > 0, and when it's 0 assert the warning is (correctly)
  absent while the editor is still live. Never flakes, but doesn't guarantee the warning is exercised — prefer the
  deterministic option above.
- No fixed sleeps; wait on real signals (KPI value, editor controls). Don't assert any cohort/SLA *values* — just
  the warning's presence and the editor being live.

## Do not
- Do not weaken the test to "editor opens" only and silently drop the forward-only coverage — keep it, made
  deterministic. Do not touch product code (the conditional warning is correct behavior). No git writes.

## Acceptance
- `bash tools/e2e.sh` green **back-to-back from varying ClickHouse states** — a clean stack (`down -v`) and a stack
  with leftover cohort data both pass `dag-sla-editor` (the test creates/confirms the instance it needs).
- The editor-live + Cancel-no-mutation checks pass unconditionally; the forward-only text is asserted with ≥1
  instance present. Other journeys + the copilot journey untouched.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_dag_sla_forward_only_flake_report.md` (uncommitted): (1)
outcome one-liner; (2) the root cause (conditional-on-instances warning + ClickHouse-leftover dependency + spec
order); (3) the fix (unconditional editor check + deterministic instance guarantee, or the conditional fallback if
chosen) — how it no longer depends on prior state; (4) verification — green from a clean `down -v` **and** from a
leftover-data stack. Half a screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `e2e/tests/dag-sla-editor.spec.ts` (+ a driver/helper
reuse) only. Deterministic, no fixed sleeps, coverage preserved.

---

## Note (not this task — two dev-env follow-ups CC surfaced)
Worth tracking separately; both are environment/determinism, not journey code:
1. **Provisioned-but-roleless personas after a restart.** The identity seed only stages *unprovisioned* emails, so
   an identity/ConfigForge restart can leave already-provisioned dev users (priya/marcus/riya) with empty
   `role_assignments` and nothing re-seeds them (CC restored them directly in Mongo to unblock). A **dev re-seed /
   repair path** for provisioned-but-roleless users would remove this whole class of "stack wedged" surprise.
2. **ClickHouse cohort data isn't reset by the seed.** The same persistence that caused this flake (and the earlier
   "stray cohort records") means observability state carries across runs. A deterministic e2e wants either a
   ClickHouse reset in the minimal-seed contract or tests that create the observability state they assert on (this
   fix does the latter for one test). Decide whether to codify a ClickHouse reset in the e2e preconditions.
