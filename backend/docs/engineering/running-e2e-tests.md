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

**The suite CREATES (and tears down — unless `E2E_KEEP` / `--keep`, see below)**
- The `ach_exposure_cohort` **cohort definition** (with the expectation-graph + closeout SLA).
- The three **ACH packs** onboarded to **active** — deterministically, **copilot-free** (see below).
- The **ACH gate-role grants** — the gates use their own `role.ach_*` roles, which the setup grants to the HITL
  persona (**marcus**) via the identity admin API *after* publishing, exactly as an operator would; teardown revokes them.
- A wizard **draft pack** per onboarding-coverage run (the Camunda-`${…}` probe).
- The **fired cases** (closed cohort instances) — tagged with the run id; cleared by your per-run DB reset.

There is **no manual "onboard ACH first" step** — the suite does it.

## Launch

```bash
docker compose -f backend/deploy/docker-compose.yml up -d          # + pega_stub + the mcp_stub servers
cd e2e && npm install && npx playwright install chromium           # one-time (deps live under e2e/)
bash tools/e2e.sh               # from repo root: self-contained — sets up ACH → runs journeys → tears down
bash tools/e2e.sh --keep        # KEEP the onboarded stack (skip teardown) — use the UI after, no re-onboard
```

### Keeping the onboarded stack (`E2E_KEEP` / `--keep`)

`tools/e2e.sh --keep` (or `E2E_KEEP=1 …`, read in `e2e/support/env.ts` → checked in `global-teardown.ts`) **skips
teardown entirely**: the ACH packs, the `ach_exposure_cohort` definition, the granted `role.ach_*` roles, and the
run's fired cohorts are **left in place** — so you can drive the UI afterwards without re-onboarding. Because setup is
create-if-absent, the **next run simply reuses** the kept stack (no double-onboard, no error). With `--keep`, data
(fired cases, published wizard packs) **accumulates** until a normal (non-keep) run tears it down or you `down -v`.
Default (flag unset) = full teardown, stack left as found.

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
4. **Then grant** the `role.ach_*` gate roles to marcus so the browser HITL persona can claim/decide the gates (the
   UI enforces role-holding). **Primary path: pending-stage** — `POST /pending-role-assignments {email, roles}`
   (priya, `role.platform.admin`); identity materialises staged roles onto the user at JIT-provision, so marcus's
   FIRST login provisions him already holding them. This is the only path that works on a **genuinely clean stack**
   (marcus not provisioned yet → not in admin `GET /users`) and it never mints marcus's token / calls his `/me`
   (preserving the no-cache-poison property). **Fallback** (marcus already provisioned, e.g. a reused `--keep`
   stack): staging returns 409 `user_exists`, so resolve the uid via admin `GET /users` and grant via
   `POST /users/{uid}/roles` (idempotent). Teardown deletes the pending stage (404 once consumed) and revokes the
   provisioned roles.

**Three details make the HITL arc close end-to-end** (learned the hard way — see the report):
- **`side_effectful` `notify_pega`** — the assess `approve_actions` gate only synthesizes a *proposed action*
  (the "Authorize all" button) for a side-effectful capability; a `read_only` one renders the empty reject-only state.
- **Trigger declared BEFORE `setBindings`** — the ADR-048 field-level `input_map` derivation runs *inside*
  `set_bindings`; if the trigger isn't declared yet, the entry capability's `case_id` maps from nothing and the
  whole chain (→ the Pega handback) carries `"unknown-case"`, so the pega-stub never advances A→B→C.
- **`notify_pega.case_id` pinned to the trigger** — `notify_pega` sits after a gateway join, so the auto-derivation
  can source `case_id` from a branch-only artifact (`request_purge_output`) absent on the taken branch → the instance
  fails "input source references artifact … not produced upstream". The trigger's `case_id` is branch-independent.

`global-teardown.ts` runs `onboard_ach.py --teardown` (revoke the granted roles, then ADR-061 clean-delete the packs
+ the cohort definition).

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

## pytest smoke (unchanged)

`bash tools/smoke.sh` (or `pytest -m smoke backend/tests/smoke`) — the fast headless layer; still assumes an
already-onboarded stack and skips per-domain when a pack isn't onboarded.
