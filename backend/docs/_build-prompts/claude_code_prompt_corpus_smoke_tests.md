# Claude Code prompt — corpus **smoke tests**: full-stack e2e, pytest, data-driven per worked-example

Author a **manually-launchable smoke suite** over the worked-example corpus
(`backend/docs/methodology/worked-examples/` — `ach_exposure`, `restaurant`, `wire_transfer`) so that after a
major change Sandeep runs **one command** and gets a green/red per domain instead of hand-driving a scenario. It
is a **full-stack e2e happy-path** smoke: against the running compose stack, fire each domain's real trigger, drive
its HITL gates, and assert the instance (and, where relevant, the cohort) reaches the expected terminal outcome.
**pytest + httpx + PyYAML — all free/OSS.** This is test scaffolding under `backend/tests/`, not application code.

The pattern already exists: `tools/demo_wire_repair.sh` is the manual smoke for one vertical (mint token → fire
trigger at the stub → poll ingestor to `accepted` → get the process instance → resolve HITL gates by persona →
poll to terminal). Generalize that into a **data-driven** suite: one small scenario spec per domain drives a
shared harness, so **adding a new worked-example is a new spec file, not new test code**.

**Scope (Sandeep's choices):** full-stack e2e; pytest; **happy path only** — one representative green scenario per
domain. Not the onboard/validate-only tier, not branch/SLA variants (leave hooks, don't build them).

## Read first
- `tools/demo_wire_repair.sh` — the reference flow to generalize: token mint (Keycloak dev CLI `amendia-dev-cli`,
  password grant, `dev-password`), the `poll` helper, the HITL resolve loop (open task → decision by mode/role →
  persona token), terminal detection (`completed`/`failed`). Reuse its endpoint defaults + role→persona mapping.
- `backend/deploy/docker-compose.yml` — service topology + ports (ingestor, agent-runtime, process-registry,
  glea-service, stub-trigger-generator, notification-service, identity, keycloak). The harness reads endpoints
  from env with these as defaults.
- `pega_stub/` (`app.py` `POST /cases`, the scenario presets incl. `credit_approve`) — the **ACH** trigger driver
  (3 segments + cohort). `stub_trigger_generator/` (`/generators/<x>/generate`) — the **wire** trigger driver.
- The three worked-examples' `ONBOARDING.md` / `README.md` / `onboarding-guide.md` + `samples/`—`sample/` dirs —
  the source of each domain's pack_keys, sample trigger, persona/role gates, and expected outcome. Derive each
  scenario spec from these (e.g. ACH: `credit_approve` → cohort `ach_exposure_cohort` closes `Released`; the wire
  reason code the demo uses; the restaurant dine-in sample).
- `backend/services/platform/glea-service/app/routers/cohorts.py` — `GET /cohorts/by-correlation/{value}` (+
  `/cohorts/{id}`) for the cohort close/outcome assertion on ACH.
- The ingestor + agent-runtime read APIs the demo already hits: `GET /ingestions/{trigger_id}` (→ `status`,
  `process_instance_id`, `resolution.pack_key`), `GET /instances/{id}` (→ `status`), `GET /hitl-tasks?...`,
  the decision endpoint. Reuse those exact shapes.

## Deliverables

### 1. `backend/tests/smoke/` — the harness (pytest, data-driven)
- **`conftest.py`** — fixtures: (a) **endpoint config** from env with compose-port defaults (override via
  `INGESTOR`/`RUNTIME`/`REGISTRY`/`GLEA`/`PEGA_STUB`/`STUB`/`KEYCLOAK`/`REALM`/…); (b) **stack readiness** — a
  session-scoped preflight that polls each service's health/root and **skips the whole suite with a clear message**
  if the stack isn't up (this is a smoke, not a deployer); (c) **token minting** — per-persona Keycloak bearers via
  the dev CLI client (mirror `mint_token`), cached; (d) an **httpx client** with a short poll helper (mirror
  `poll`, terminal = `completed`/`failed`).
- **`scenarios.py`** — load every `scenarios/*.yaml` and expose them for `pytest.mark.parametrize` (id = domain),
  so the corpus drives the tests.
- **`drivers.py`** — a small **trigger-driver registry** keyed by `trigger.kind`:
  `pega_stub` (`POST {PEGA_STUB}/cases`), `stub_generator` (`POST {STUB}/generators/<name>/generate`), and a
  `direct_trigger` fallback (POST a sample payload to the stub/ingestor) for domains that need it (e.g. restaurant
  — pick whichever its onboarding doc uses). Each driver fires the trigger and returns the correlation/trigger id.
- **`hitl.py`** — generalize the demo's resolve loop: while the instance isn't terminal, pull the next open HITL
  task, pick the **persona token by the task's role** (from the scenario's `hitl` map, default persona otherwise),
  and POST the decision (`approve`, or `complete` for `manual`). Bounded by the scenario timeout.
- **`test_smoke.py`** — one parametrized test per scenario: preflight the expected `pack_keys` are onboarded
  (`GET {REGISTRY}/packs`) → **skip with a clear "onboard <pack> first" message** if not; fire the trigger;
  poll ingestor → `accepted` + `process_instance_id`; assert `resolution.pack_key` matches; drive HITL to terminal;
  **assert `status == expected.instance_status`** (happy path: `completed`); for cohort domains, poll
  `GET {GLEA}/cohorts/by-correlation/{value}` and assert `state`/`outcome` match `expect.cohort`. Mark
  `@pytest.mark.smoke`.

### 2. Scenario specs — one happy path per domain (`backend/tests/smoke/scenarios/`)
Declarative YAML; the schema is what the harness reads (finalize field names, keep semantics):
```yaml
domain: ach_exposure
pack_keys: [ach-exposure-assess, ach-decision-enforce, ach-closeout]   # preflight: must be onboarded
trigger: { kind: pega_stub, request: { scenario: credit_approve } }
correlation: case_id
hitl: { "role.exposure_exception_pop_part1.pop": priya }               # role -> persona (for token mint)
expect:
  instance_status: completed
  cohort: { correlation_from: case_id, state: closed, outcome: Released }   # omit for non-cohort domains
timeout_s: 150
```
Provide `ach_exposure.yaml` (pega_stub credit_approve → cohort closed/Released), `wire_transfer.yaml`
(stub_generator, the demo's reason code → completed), `restaurant.yaml` (its dine-in trigger → completed). Derive
pack_keys / personas / expected outcome from each domain's onboarding doc; if a domain isn't onboardable/runnable
as-is, still ship its spec but mark it `skip: true` with a reason (don't silently drop it).

### 3. Launcher + deps + docs
- **`tools/smoke.sh`** — check the stack is reachable, then `pytest -m smoke -v backend/tests/smoke` (pass through
  args, e.g. `-k ach`), and print a one-line per-domain PASS/FAIL summary. Non-zero exit on any failure.
- **Deps** — add `pytest`, `httpx`, `pyyaml` to the smoke suite's dev deps (a `backend/tests/smoke/requirements.txt`
  or the existing test extra). All free/OSS; no new services.
- **`backend/tests/smoke/README.md`** — how to launch (`docker compose … up` + onboard packs → `tools/smoke.sh`),
  what "green" proves, the env overrides, and **how to add a domain** (drop a `scenarios/<domain>.yaml`).

## Do not
- Do not onboard via the **copilot/LLM** path in the test (non-deterministic). The smoke runs against an
  already-deployed **and onboarded** stack; a missing pack is a clean **skip with guidance**, not a failure.
  (Deterministic self-contained onboarding via `POST /packs` with committed manifests is a noted future extension,
  not this task.)
- Do not put per-domain logic in the test body — everything domain-specific lives in the **scenario spec** + the
  keyed drivers. Adding a domain must need **no** change to `test_smoke.py`.
- Do not add paid/proprietary test tooling or new runtime services. Do not assert on timing-fragile internals; poll
  with sane timeouts and assert terminal state/outcome only.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance
- With the compose stack **up and the three domains onboarded**, `bash tools/smoke.sh` (or
  `pytest -m smoke -v backend/tests/smoke`) runs **3 scenarios, one per domain, all green** in a couple of minutes:
  ACH reaches `completed` **and** its cohort closes `Released`; wire reaches `completed`; restaurant reaches
  `completed`.
- With the stack **down**, the suite **skips** with a clear "stack not reachable" message (no confusing errors).
  With a domain's pack **not onboarded**, that scenario **skips** with "onboard <pack_key> first" — the others run.
- Adding a new `scenarios/<domain>.yaml` makes it run with **no code change** (proven by a trivial 4th spec in the
  report, then removed).
- `pytest -m smoke` is the only entrypoint; nothing domain-specific is hardcoded in Python. httpx/pyyaml/pytest
  only.

## Final step — implementation report (required)
Write `backend/docs/_build-reports/claude_code_prompt_corpus_smoke_tests_report.md` (uncommitted): (1) outcome
one-liner; (2) the harness layout (conftest fixtures, scenario loader, driver registry, HITL resolver) + how it
generalizes the demo; (3) the scenario-spec schema + the three specs' actual values (trigger kind, personas,
expected outcome); (4) the launcher + deps + how to add a domain; (5) verification — the exact command + the
green run (per-domain PASS), the stack-down skip, and the missing-pack skip; (6) follow-ups (self-contained
`POST /packs` onboarding tier, branch/SLA-breach variants, CI wiring). One screen.

## Working agreement
No git write commands — leave the tree dirty for Sandeep. `backend/tests/smoke/` + `tools/smoke.sh` only; reuse the
`demo_wire_repair.sh` token/poll/HITL patterns and the existing read APIs. Data-driven (spec per domain), free/OSS
(pytest+httpx+pyyaml), full-stack happy-path, degrading (skip, don't error) when the stack or a pack is absent.
