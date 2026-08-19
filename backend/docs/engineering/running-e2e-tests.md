# Running the e2e tests (Playwright UI + pytest smoke)

Two layers over the running compose stack:

- **Playwright full-system e2e** (`e2e/` — a **top-level** suite, frontend + backend + stubs + DB, with its own
  `package.json`) — the **primary** e2e: drives the real webui→backend as a user. **Self-contained**: from an empty,
  minimally-seeded stack it onboards the ACH domain itself, runs the journeys, and tears down. It is not part of the
  webui package; its only cross-boundary tie is the `webServer`, which serves the webui via `vite dev` from `../webui`.
- **pytest smoke** (`backend/tests/smoke/`) — the fast headless check (same scenario specs).

## The minimal-seed contract

Each run may start from an **empty, minimally-seeded** stack (`docker compose … down -v` → `up`). The seed must
provide everything onboarding + execution *need*, but **no packs / no cohort definitions / no instances**:

**The minimal seed MUST provide**
- **Keycloak** realm `amendia-dev` + the dev users: **priya** (`role.process.owner` + `role.platform.admin`),
  **marcus** (ops-approver), **riya** (ops-analyst); the `amendia-dev-cli` client (password grant).
- **identity** service (JIT-provisions the personas from their tokens).
- The core services up: ingestor, agent-runtime, process-registry, glea-service, notification-service, stub-trigger-generator, pega-stub.
- The **five `mcp_stub` capability servers** reachable on the compose network: `ach-assess-mcp:8075`,
  `ach-enforce-mcp:8076`, `ach-closeout-mcp:8077` (ACH), plus `restaurant_dinein` + `wire_transfer_exception`.
- An **empty registry** (no packs, no cohort definitions).

**The deterministic gate CREATES (and always tears down)**
- The `ach_exposure_cohort` **cohort definition** (with the expectation-graph + closeout SLA).
- The three **ACH packs** onboarded to **active** — deterministically, **copilot-free** (see below).
- The **ACH gate-role grants** — the gates use their own `role.ach_*` roles, which the setup grants via the identity
  admin API *after* publishing, **distributed EXCLUSIVELY across two humans** (`_roles_by_persona`): the enforce
  approval role → **marcus** (segment B), the assess + closeout review roles → **riya** (segments A + C). priya only
  onboards + owns the cohort, then steps out. This split lets the `ach-lifecycle` journey drive the segments as two
  distinct humans (assessor/closeout reviewer ≠
  enforce approver). Teardown revokes both personas' roles.
- A wizard **draft pack** per onboarding-coverage run (the Camunda-`${…}` probe).
- The **fired cases** (closed cohort instances) — tagged with the run id; cleared by your per-run DB reset.

There is **no manual "onboard ACH first" step** — the suite does it.

## Launch

```bash
docker compose -f backend/deploy/docker-compose.yml up -d          # + pega_stub + the mcp_stub servers
cd e2e && npm install && npx playwright install chromium           # one-time (deps live under e2e/)
bash tools/e2e.sh               # THE CI GATE (repo root): self-contained — sets up ACH → runs journeys → tears down
bash tools/e2e-copilot.sh       # NON-BLOCKING copilot lifecycle — real autopilot onboard; RETAINS everything; skips w/o a model
```

**Two commands, no flags.** The old `--keep` / `--copilot` / `--keep-copilot` flags (and their `E2E_KEEP` /
`E2E_COPILOT` / `E2E_KEEP_COPILOT` env) are **gone**. `tools/e2e.sh` is the deterministic gate (always tears down);
the copilot path is now its own command below.

### The copilot lifecycle command (`tools/e2e-copilot.sh`)

A **separate, non-blocking** command (own `playwright.copilot.config.ts`, own `global-setup.copilot.ts` — logins
only, **no** deterministic ACH onboarding, **no** teardown) that proves the **real copilot onboarding path** end to
end: `e2e/tests/ach-copilot-lifecycle.spec.ts` drives the LLM autopilot (`/registry/onboard`) to onboard the 3 ACH
segments (fresh pack keys per run), sets cohort membership, distributes the gate roles read from the packs, creates
its **own** cohort definition `ach_copilot_cohort` (distinct from the gate's `ach_exposure_cohort`, so the two
commands never collide) over the **captured** pack keys, and runs the **same 3 pega flows** the gate does — over
**copilot-inferred** packs. It:

- **costs real model calls and is slow** (3 live LLM onboardings + 3 flows) — for manual / nightly runs;
- **reads everything from the live packs and asserts stable outcomes only** — the gate roles, the human-artifact
  schemas, and the pack keys are all copilot-inferred and **vary per run**, so nothing inferred is hardcoded or
  asserted. Two consequences the spec handles: (a) each **manual gate's value is SYNTHESIZED from its inferred
  artifact schema** (`support/copilot.ts`) — the fix for the de-risk's `422` (a copilot-invented
  `release_authorization` schema a hardcoded value couldn't satisfy); (b) the copilot often infers a **4-eyes
  `distinct_actor` SoD within enforce** (e.g. AuthorizeRelease vs PrepareRelease) that a *single* enforce approver
  cannot satisfy — so **every gate role is granted to BOTH marcus and riya** and each gate is driven by the
  **SoD-aware picker** (marcus first; riya provides the second signature when marcus is SoD-excluded). priya (owner)
  drives no gate. See `backend/docs/_build-reports/ach_copilot_derisk_findings.md`;
- asserts the stable lifecycle outcomes: each pack publishes **active**; both process humans hold every gate role so
  a 4-eyes SoD is satisfiable while priya (owner) holds none; **Members 3** + the DAG + the enforce→closeout
  **external** SLA; and each of `credit_approve` / `debit_reject` / `late_closeout` reaches **3 members / closed**
  (Released / Purged / external-breach→Released). A cohort that stalls below 3 members is a real failure;
- **skips (never fails) when the stack has no copilot model** — `copilot/generate` → `502 copilot_llm_unavailable`
  → the whole journey skips with a clear message;
- **RETAINS everything** (no teardown): the onboarded packs, the cohort + instances, and the granted roles stay for
  inspection. **Re-run needs a clean DB** (`down -v` → `up`): because it retains, a second run finds its
  `ach_copilot_cohort` already present and **skips with a "wipe the DB" message** (fresh pack keys avoid the
  runtime's non-evicting bundle-cache, but the cohort definition is the clean-stack sentinel). Its own id means it
  never disturbs — and is never disturbed by — the deterministic gate's `ach_exposure_cohort`;
- **never gates CI** — it is excluded from `tools/e2e.sh` via the config's `testIgnore`.

## How the deterministic setup works (no copilot/LLM)

`e2e/global-setup.ts` runs `fixtures/onboarding/onboard_ach.py` (idempotent; create-only-if-absent). The
driver uses the registry's **technical onboarding API** — MCP introspection + the rule-based `infer_draft` (both
deterministic) — never the LLM copilot:

1. `POST /cohort/definitions` → the cohort definition.
2. Per pack: create session → attach BPMN → **introspect** the MCP (`transport=streamable_http`) + `setCapabilities`
   (propagating each tool's `suggested_side_effect` — `notify_pega` is `side_effectful`) → declare the manual gates'
   **human artifact schemas** → declare the **trigger** (corpus schema's `json_schema`) → `setBindings` (capability
   + manual/human, with the enforce gateway's `output_name`) → `setTriage` (`when:{all:[{field:request_type,…}]}`)
   → `setPolicies` (roles + gateway-vars) → `assemble` → `commit` → set `cohort-membership`.
3. **Per-pack domain** (`ach_assess` / `ach_enforce` / `ach_closeout`) so the shared `notify_pega` tool yields
   DISTINCT cap/artifact ids per pack (else the 2nd pack's commit collides on the 1st's registered copies).
3a. **Faithful side-effect gating** (Amendia rule: any side-effectful activity is human-gated — the assemble
   hitl-guard REQUIRES an `approve_actions` gate on a `side_effectful` capability). Each segment gates its
   side-effectful **action tools** (`ACTION_TOOLS` per MCP stub): **A** `notify_pega` (the handback approval);
   **B** `prepare_release` / `request_purge` / `notify_pega` + the `AuthorizeRelease` / `AuthorizePurge` decision
   userTasks; **C** `mark_completed` / `purge_working_data` / `notify_pega` + the `ReviewArtifacts` userTask. So
   **every segment has ≥1 human gate**, all of which must be driven for the cohort to advance A→B→C. **No manifest
   SoD**: once the actions are gated, an intra-enforce `distinct_actor` pairing an action gate with the human
   `AuthorizeRelease` would exclude the single enforce approver from the second gate (`compute_sod_excluded` excludes
   a HUMAN who acted on a sibling) and stall B — so SoD is CROSS-SEGMENT (enforce approver ≠ assess/closeout
   reviewer), enforced by the exclusive role distribution.
4. **Then grant** the `role.ach_*` gate roles — the runtime AND the UI enforce role-holding at claim
   (403 `caller lacks required role`), so each gate is driven by a role-holder. Distributed **EXCLUSIVELY** across
   two humans (`_roles_by_persona`): `role.ach_decision_enforce.approver` → **marcus** (B); the assess + closeout
   review roles → **riya** (A + C). priya only onboards + owns the cohort. **Primary path: pending-stage** —
   `POST /pending-role-assignments {email, roles}` (priya, `role.platform.admin`); identity materialises staged
   roles at JIT-provision, so each persona's FIRST login already holds them (clean-stack safe; no `/me` cache poison).
   **Fallback** (already provisioned): 409 `user_exists` → resolve uid via admin `GET /users`, grant via
   `POST /users/{uid}/roles`. Teardown deletes the pending stage (404 once consumed) and revokes the roles.

**Three details make the HITL arc close end-to-end** (learned the hard way — see the report):
- **`side_effectful` `notify_pega`** — the assess `approve_actions` gate only synthesizes a *proposed action*
  (the "Authorize all" button) for a side-effectful capability; a `read_only` one renders the empty reject-only state.
- **Trigger declared BEFORE `setBindings`** — the ADR-048 field-level `input_map` derivation runs *inside*
  `set_bindings`; if the trigger isn't declared yet, the entry capability's `case_id` maps from nothing and the
  whole chain (→ the Pega handback) carries `"unknown-case"`, so the pega-stub never advances A→B→C.
- **`notify_pega.case_id` pinned to the trigger** — `notify_pega` sits after a gateway join, so the auto-derivation
  can source `case_id` from a branch-only artifact (`request_purge_output`) absent on the taken branch → the instance
  fails "input source references artifact … not produced upstream". The trigger's `case_id` is branch-independent.

`global-teardown.ts` always runs `onboard_ach.py --teardown` (revoke the granted roles, then ADR-061 clean-delete the
packs + the cohort definition) — the deterministic gate leaves the stack as found. (The copilot lifecycle command
uses a separate config with **no** teardown, so it retains everything.)

> **Local re-run caveat (not a CI concern):** agent-runtime caches the compiled pack graph by `(pack_key, version)`
> for the life of the process. Re-onboarding the *same* `1.0.0` after changing the pack shape (e.g. while iterating
> on `onboard_ach.py`) is masked by that cache — `docker restart deploy-agent-runtime-1` to pick up the new graph.
> A real run from a fresh stack has an empty cache, so this never bites CI.

## Degrading

Backend/webui down → the whole suite **skips** (global-setup writes a skip flag). If setup can't complete, the ACH
**execution** journeys skip cleanly ("ACH setup incomplete") — never a hard fail. The `cohorts` test skips (not
fails) if the definition isn't present.

> **Known cold-stack gap (unrelated to onboarding):** `dag-sla-editor`'s "forward-only warning" assertion needs the
> `ach_exposure_cohort` definition to have **≥1 cohort instance** — the webui renders that banner only when
> `instances.length > 0` (`CohortDefinitionPage.tsx`). On a truly clean `down -v` this test runs **before** `hitl-arc`
> fires the first case, so it fails with an empty definition; it passes on any warm stack (or a second run, once an
> instance exists). Making it skip-when-no-instances is a separate test change, out of scope for the role-grant fix.

## pytest smoke (files unchanged)

`bash tools/smoke.sh` (or `pytest -m smoke backend/tests/smoke`) — the fast headless layer; still assumes an
already-onboarded stack and skips per-domain when a pack isn't onboarded. Its files are untouched by the ACH e2e.

> **Role-enforcement note:** the runtime enforces role-holding at claim (`403 caller lacks required role`). The ACH
> e2e distributes gate roles EXCLUSIVELY (marcus = enforce, riya = assess/closeout), so a headless driver that acts
> as a single persona for every gate (the smoke's `ach_exposure.yaml` has `default_persona: marcus`, `roles: {}`)
> cannot claim the assess/closeout gates against an e2e-onboarded stack. To run the ACH smoke against such a stack,
> map the gate roles to their holders in the scenario's `hitl.roles` (e.g. assess/closeout reviewer → riya, enforce
> approver → marcus) — a smoke-scenario change, deliberately not made here.
