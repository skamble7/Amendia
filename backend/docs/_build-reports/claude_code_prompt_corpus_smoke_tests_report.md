# Corpus smoke tests — full-stack, data-driven, per worked-example: report

## 1. Outcome

`backend/tests/smoke/` is a **manually-launchable** full-stack happy-path smoke over the worked-example corpus:
one command (`bash tools/smoke.sh` / `pytest -m smoke`) fires each domain's **real** trigger against the running
compose stack, drives its HITL gates by persona, and asserts the instance (or cohort) reaches the expected
terminal outcome — **green/red per domain**. It generalizes `tools/demo_wire_repair.sh` into a data-driven suite:
**adding a worked-example is a new `scenarios/<domain>.yaml`, not new test code** (proven). `pytest`+`httpx`+
`pyyaml` only. Verified live: **ACH passes** (cohort `closed`/`Released`), and wire/restaurant **skip cleanly**
when not onboarded — exit 0.

## 2. Harness (generalizes the demo)

- **`config.py`** — every endpoint from env with **compose host-port defaults** (`18082` ingestor, `18083`
  runtime, `18084` registry, `18090` glea, `18081` stub, `9095` pega-stub, `8087` keycloak, realm `amendia-dev`,
  dev CLI client). **`client.py`** — reachability check, Keycloak token minting (password grant via the dev CLI
  client, cached per persona), the `/me` user-id lookup (for SoD), and a `poll()` (mirrors the demo's `poll`;
  terminal = `completed`/`failed`).
- **`conftest.py`** — session fixtures + a **stack-readiness preflight** that **skips the whole suite** with a
  clear message when a core service is down (a smoke, not a deployer).
- **`scenarios.py`** — loads every `scenarios/*.yaml` into a typed `Scenario` for `parametrize` (id = domain).
- **`drivers.py`** — a **trigger-driver registry** keyed by `trigger.kind`: `pega_stub` (`POST /cases`),
  `stub_generator` (`POST /generators/<id>/generate`), `direct_trigger` (fallback `POST /triggers`). Each fires
  and returns a `Handle(correlation, trigger_id)`.
- **`hitl.py`** — the demo's gate loop, generalized: per open task pick the persona for its role (spec map, else
  default) **SoD-aware** (skip a persona in the task's `sod.excluded_users`), claim, and decide (`complete` for
  `manual`, else `approve`); **recover a stuck `claimed` task** by re-deciding as its assignee; and for a manual
  gate that produces an artifact, send the **spec-provided output** as `edits` (`{correlation}` interpolated).
- **`test_smoke.py`** — the ONE parametrized test: preflight packs onboarded (`GET /packs?status=active`) → fire
  → for a single-instance domain poll the ingestor to `accepted` + assert `resolution.pack_key`, drive HITL,
  assert `instance == completed`; for a cohort domain poll `GET /cohorts/by-correlation/{value}`, resolve each
  member's gates, assert `state`/`outcome` + no failed members. Nothing domain-specific lives here.

## 3. Scenario-spec schema + the three specs

```yaml
domain: … ; pack_keys: […]                      # preflight: must be active in the registry
trigger: { kind: pega_stub|stub_generator|direct_trigger, request: {…} }
correlation: case_id|trigger_id                 # where the case handle is read from the fire result
hitl: { default_persona, roles:{role→persona}, personas:[pool], outputs:{element_id→edits} }
expect: { instance_status: completed, cohort: {state, outcome} }   # cohort omitted for single-instance
timeout_s: … ; skip: false                      # skip:true+skip_reason ships-but-doesn't-run a non-runnable domain
```

- **wire_transfer** — `stub_generator` (`wire`, reason `AC01`) → the seeded `wire-repair-standard`; approver gate
  `role.payments.ops_approver → marcus`, default `riya`; expect `instance=completed`.
- **ach_exposure** — `pega_stub` (`credit_approve`) → cohort `ach_exposure_cohort`; SoD pool `[marcus, riya]`;
  **outputs** for the two manual gates the onboarding uses (`Task_AuthorizeRelease → release_authorization`,
  `Task_ReviewArtifacts → review_decision: {approved, disposition_confirmed: released}`); expect cohort
  `closed`/`Released`.
- **restaurant** — `stub_generator` (`dine_in`, happy) → `restaurant-dinein`; dining roles → `riya/marcus/priya`;
  expect `instance=completed`. Not seeded → skips until onboarded (dinein-mcp + dining roles), per its spec note.

## 4. Launcher + deps + adding a domain

- **`tools/smoke.sh`** — checks deps, runs `pytest -m smoke -v backend/tests/smoke "$@"` (pass-through, e.g.
  `-k ach`), prints a **per-domain PASS/FAIL/SKIP summary**, non-zero exit on any failure.
- **Deps** — `backend/tests/smoke/requirements.txt` (`pytest`, `httpx`, `pyyaml` — all free/OSS).
- **Add a domain** — drop `scenarios/<domain>.yaml`; the harness picks the driver by `trigger.kind`, resolves
  HITL by role, and asserts per `expect`. A genuinely new mechanism is a new entry in `drivers.py::DRIVERS`.

## 5. Verification (against the live stack)

- `bash tools/smoke.sh` → per-domain summary: **`ach_exposure: PASSED`** (cohort `state=closed outcome=Released
  rollup={done:3, running:0, failed:0}`, full A→B→C→close in ~19s), `wire_transfer: SKIPPED`, `restaurant:
  SKIPPED` (not onboarded in this stack), **exit 0** (skips don't fail).
- **Stack-down skip:** `INGESTOR=http://localhost:19999 pytest -m smoke` →
  `SKIPPED … stack not reachable (ingestor down) — bring it up: docker compose … up -d`.
- **Missing-pack skip:** wire/restaurant → `SKIPPED … onboard ['wire-repair-standard'] first (not active …)`.
- **Add-a-domain = no code change:** a throwaway 4th spec (`_probe_demo.yaml`) was auto-collected as
  `test_corpus_smoke[probe_demo]` and ran (skipped with its guidance) with zero Python change, then removed.
- Command used: `pytest -m smoke -v -o addopts= -p no:cacheprovider backend/tests/smoke` (deps satisfied by any
  venv with pytest+httpx+pyyaml).

## 6. Follow-ups

- **Self-contained onboarding tier** — a deterministic `POST /packs` (committed manifests) pre-step so a fresh
  stack goes green without the wizard (the copilot/LLM path is deliberately excluded — non-deterministic).
- **Branch / SLA-breach variants** — e.g. ACH `late_closeout` (at-risk→breach→arrived-late→Released), wire
  reject/return, restaurant allergen-conflict — hooks exist (drivers + spec), not built (happy-path only).
- **Generic manual-output synthesis** — today a manual gate that authors an artifact takes its output from the
  spec's `hitl.outputs` (case values interpolated). A schema-driven synthesizer (fetch the artifact schema, fill
  required fields) would remove that per-gate spec data — noted, not built.
- **CI wiring** — the suite is manual by design; a nightly job against an ephemeral onboarded stack is a natural
  next step (`pytest -m smoke`, non-zero exit gates it).
