# Claude Code prompt — pega-stub: add a 4th scenario that **breaches the cohort closeout SLA** (delayed Segment C)

Dev-scaffolding change to the mock Pega orchestrator (`pega_stub/`) for the **ADR-064 SLA e2e**. Today the stub
fires Segment A -> B -> C immediately on each `notify_pega` handback. Add a **4th scenario** that behaves like a
normal approve case through A and B, then **delays the Segment C (closeout) trigger past the cohort's
enforce->closeout arrival SLA (20s)** — so the SLA breaches (owner=external), the closeout then arrives *late*
(recorded `arrived_late`), and the case still closes. This exercises the full at-risk -> breach -> late-arrival ->
close arc against the ACH cohort. **pega_stub only.**

## Why

The e2e declares (via the new cohort DAG/SLA editor) an **arrival SLA on the `ach-decision-enforce ->
ach-closeout` hop, 20s, owner external** — "after enforce hands back, Pega must invoke closeout within 20s."
To breach it deterministically we need a scenario where the stub is *late* firing the closeout trigger. A ~25s
delay (> the 20s deadline) breaches at 20s, then the closeout arrives at ~25s.

## Read first

- `pega_stub/src/pega_stub/scenarios.py` — `SCENARIOS` (`credit_approve`/`debit_reject`/`route_uw`) and the
  payload builders. Add the 4th preset here.
- `pega_stub/src/pega_stub/orchestrator.py` — `Orchestrator.handback`: the `n == 2` branch fires Segment C
  immediately. This is where the optional delay hooks in. Note it's `async` and runs under the FastAPI event
  loop, so the delay MUST be non-blocking (a scheduled task) — never `await asyncio.sleep(25)` inline (that would
  hang the handback HTTP response for 25s and look stuck).
- `pega_stub/src/pega_stub/{app.py,ui.py}` — the `POST /cases` scenario input + the status UI scenario picker
  (so the new scenario is selectable and visible).
- `pega_stub/tests/test_orchestration.py` + `conftest.py` — the fake-submit test harness to mirror.

## Deliverables

1. **New scenario preset (`scenarios.py`).** Add `late_closeout` — same shape as `credit_approve` (approve path
   -> Released) **plus** an opt-in delay field, e.g.:
   ```python
   "late_closeout": {
       "company": "DELTA-FREIGHT", "exposure_type": "credit",
       "credit_amount": 335000.0, "credit_limit": 300000.0, "debit_amount": 0.0, "debit_limit": 200000.0,
       "overage": 35000.0, "rbo_decision": "approve",
       "closeout_delay_seconds": 25,   # > the 20s enforce->closeout arrival SLA -> breach, then late arrival
   },
   ```
   The existing three scenarios have **no** `closeout_delay_seconds` (treat absent/0 as "fire immediately" — the
   current behaviour, unchanged). Optionally allow an env override `CLOSEOUT_DELAY_SECONDS` (via `config.py`) to
   retune the delay without editing the preset — nice for demos; if you add it, it overrides the preset value
   when set.

2. **Delayed Segment C fire (`orchestrator.py`, `n == 2` branch).** Read
   `delay = preset.get("closeout_delay_seconds", 0)` (env override applied). If `delay > 0`: **schedule** the
   Segment-C submit for `delay` seconds later via `asyncio.create_task(...)` (a small `_fire_c_later` coroutine
   that `await asyncio.sleep(delay)` then submits C and records `triggers["C"]`/history), and return the handback
   response **immediately** — do not block. If `delay <= 0`: fire C immediately, exactly as today. Preserve:
   - idempotency — Segment C is submitted **exactly once** (schedule at most one task; a duplicate B-handback is
     already a no-op via the tracked `completed` list);
   - the `n == 3` close path is unchanged (when C completes and hands back, the close message still fires and the
     cohort drains);
   - a sensible `step` while the delay is pending (e.g. `"C"` or `"C_pending"`), and a history entry noting the
     scheduled delay so the stub UI/`GET /cases/{id}` shows *why* C is late.
   - Handle shutdown/edge cases gracefully (a case closed before the delayed task fires -> the delayed submit
     no-ops; don't crash the loop).

3. **UI/API surface (`ui.py`/`app.py`).** The `late_closeout` scenario is selectable in the status UI picker and
   accepted by `POST /cases`; the UI shows the delay/late-C state (reuse the existing history rendering).

4. **Tests (`test_orchestration.py`).** Add a test that with `late_closeout`, after the B handback, Segment C is
   **not** submitted synchronously and **is** submitted after the delay (make it deterministic — inject a tiny
   delay, or monkeypatch `asyncio.sleep`, or expose the delay as an injectable so the test doesn't wait 25s), and
   that the close still fires after C's handback. Assert the existing scenarios still fire C immediately
   (delay-absent path unchanged).

## Do not

- Do not change the segment payload shapes, `request_type`s, the close payload/schema, or the trigger-store
  submit path — only *when* Segment C is submitted.
- Do not touch anything outside `pega_stub/`. No backend/webui/cohort changes.
- Do not block the event loop (no inline long `sleep` in the request path).
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- `POST /cases {"scenario":"late_closeout"}` -> Segment A fires, B fires on A's handback, and Segment C fires
  **~25s after B's handback** (not immediately); after C completes the `process_completed` close fires and the
  case reaches `closed`. The other three scenarios fire C immediately (unchanged).
- `pytest` (pega_stub) green incl. the new delayed-fire test + the unchanged-immediate assertion, deterministic
  (no real 25s wait in tests).
- **Reviewer note:** live after `docker compose -f pega_stub/deploy/docker-compose.yml build && up -d`.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_pega_stub_sla_breach_scenario_report.md` (uncommitted):
(1) outcome one-liner; (2) the `late_closeout` preset + the `closeout_delay_seconds` convention (+ env override
if added); (3) the non-blocking delayed-fire wiring in `handback` and how once-only/idempotency + the close path
are preserved; (4) UI/API surface; (5) verification — exact `pytest` command + results, and how the delay is made
deterministic in tests. One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. pega_stub only; reuse the existing scenario/handback
patterns and the fake-submit test harness. Non-blocking delay, once-only C, close path intact.
