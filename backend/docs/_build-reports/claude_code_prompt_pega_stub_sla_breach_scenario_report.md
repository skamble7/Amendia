# pega_stub — `late_closeout` scenario (delayed Segment C → cohort SLA breach): report

Dev-scaffolding change to the mock Pega orchestrator for the **ADR-064 SLA e2e**. **pega_stub only.**

## 1. Outcome

A 4th scenario, **`late_closeout`**, runs a normal approve case through Segment A → B, then fires the Segment C
(closeout) trigger **~25s late** (non-blocking) — past the cohort's `ach-decision-enforce → ach-closeout`
arrival SLA (20s). So the SLA breaches (owner=external), the closeout then arrives late (runtime records
`arrived_late`), and the case still closes. The other three scenarios fire C immediately, unchanged. pega_stub
`pytest` **15 passed** (+4), deterministic (no real 25s wait).

## 2. The `late_closeout` preset + `closeout_delay_seconds` convention

- `scenarios.py`: `late_closeout` = same shape as `credit_approve` (approve path → Released) plus
  `"closeout_delay_seconds": 25`. The other three presets omit the key — **absent/0 → fire immediately**
  (current behaviour, unchanged). Payload shapes / `request_type`s / the close schema are untouched.
- Env override (`config.py`): `CLOSEOUT_DELAY_SECONDS` → `settings.closeout_delay_override`. When `> 0` it
  overrides the preset's `closeout_delay_seconds` (retune the demo without editing code); `0` (default) → use
  the preset. Never affects a scenario that declares no delay. Resolved by `_closeout_delay(preset)`.

## 3. Non-blocking delayed-fire wiring (`orchestrator.py`, `n == 2` branch)

- The C-submit was factored into `_fire_c(case)` (once-only: skips if the case is closed or C already fired —
  `"C" in case["triggers"]`). The `n == 2` branch now: sets `instruction`, reads `delay = _closeout_delay(preset)`,
  then:
  - `delay <= 0` → `await self._fire_c(case)` immediately (exactly as before);
  - `delay > 0` → set `step = "C_pending"` + `closeout_delay_seconds`, append a `scheduled` history entry, and
    `self._schedule(self._fire_c_later(case_id, delay))` — then **return the handback response immediately**.
    The delay never blocks the event loop / the HTTP response.
- `_fire_c_later(case_id, delay)` `await self._sleep(delay)` then re-fetches the case and calls `_fire_c`.
  **Once-only / idempotency preserved:** the schedule happens only in the `n == 2` branch, which runs exactly
  once per case (a duplicate B-handback is a no-op — `"B"` already in `completed`), and `_fire_c`'s guard is a
  second belt-and-braces check. **Edge cases handled:** a case closed/removed before the timer fires → no-op; a
  cancelled sleep (shutdown) → no-op (no loop crash). Scheduled tasks are tracked in `self._tasks` (+ a `drain()`
  helper) so they can be awaited/cleaned up.
- **Close path unchanged:** when the late C hands back, `n == 3` fires the `process_completed` close exactly as
  before and the cohort drains to `closed`.
- The `sleep` seam is injected on `Orchestrator(submit=..., sleep=asyncio.sleep)` — real sleep in production,
  collapsed in tests.

## 4. UI / API surface

- `/scenarios` returns `sorted(S.SCENARIOS)` → `late_closeout` is automatically selectable in the status-UI
  picker and accepted by `POST /cases` (validated by `start_case`).
- `ui.py`: the progress pills mark C as **current** while `step === "C_pending"`, and the decision cell shows
  `⏳ closeout +25s (SLA breach)` (from the `closeout_delay_seconds` field) so the delay/late-C state is visible;
  reuses the existing history/`GET /cases/{id}` rendering (a `scheduled` history entry explains *why* C is late).

## 5. Verification

- `cd pega_stub && uv run --extra dev pytest` → **15 passed** (+4):
  - `test_non_delayed_scenarios_fire_c_immediately` — the three existing presets still fire C synchronously on
    the B handback (delay-absent path unchanged);
  - `test_late_closeout_defers_segment_c_then_closes` — after B, C is **not** submitted synchronously (only A+B
    in the store) and `step == "C_pending"`; after `drain()` the closeout fires; the C handback then fires the
    `process_completed` close and the case reaches `closed`;
  - `test_late_closeout_schedules_c_exactly_once` — a duplicate B handback schedules no second C (exactly one
    `ach.closeout_requested`);
  - `test_late_closeout_selectable_via_api` — `/scenarios` lists it and `POST /cases` starts it (Segment A).
- **Determinism:** the delay is made deterministic by injecting a no-op `sleep` (`Orchestrator(..., sleep=_instant)`)
  and awaiting the scheduled task via `orch.drain()` — no real 25s wait, no monkeypatching of `asyncio`.
- **Reviewer note:** live after `docker compose -f pega_stub/deploy/docker-compose.yml build && up -d`. For the
  full e2e, register the ACH cohort's `expectation_graph` (via the P4 editor) with the `ach-decision-enforce →
  ach-closeout` arrival SLA at 20s, owner external, then run `late_closeout`.
