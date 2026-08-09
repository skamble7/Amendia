# ADR-063 fix — suppress the stray `closing`-after-`closed` cohort event: report

## 1. Outcome

Fixed. `CohortService.close()` no longer emits a trailing `closing` when a concurrent last-member drain already
finalized the cohort to `closed` in the `begin_close`→`finalize` gap. The lifecycle stream can no longer carry
`closed` then `closing`; the "members still running" path still emits `closing` exactly once. Exactly-one-`closed`
and the drain are untouched.

## 2. Approach — re-read guard (not tri-state)

Took the **re-read guard** (the explicitly-acceptable option): the smallest change, confined to
`cohort_service.py`, no repo signature churn. After a failed `finalize_if_drained`, `close()` re-reads the cohort
(`repo.get`, already existing) and emits `closing` **only when `state == CLOSING`**; if a concurrent drain already
moved it to `CLOSED`, it stays silent. I did not take the tri-state route because it would change
`finalize_if_drained`'s contract (or add a sibling) for a one-caller benefit — the residual TOCTOU is harmless
here: once `CLOSED`, the state is terminal, so the re-read can only see `CLOSING` (still running) or `CLOSED`
(drain won), never a value that would wrongly emit `closing`.

The atomic `begin_close` / `finalize_if_drained` conditionals and `on_member_terminal` are **unchanged** — the
exactly-one-`closed` guarantee still rests on the single `{state: CLOSING, active_member_count: 0} → CLOSED`
conditional that only one caller can match.

## 3. New ordering test + deterministic interleave

`tests/test_cohort_close_drain.py::test_close_finalize_losing_to_drain_emits_no_trailing_closing`. The interleave
is **forced deterministically**, not by scheduler luck: the test monkeypatches the repo's `finalize_if_drained`
so that, on `close()`'s first finalize attempt, it runs the last member's `on_member_terminal` drain **to
completion** (which wins the real finalize → `CLOSED`, emits `closed`) and only then delegates to the real
finalize (which now matches nothing). A one-shot flag prevents recursion when the drain itself calls finalize.
Asserts: exactly one `closed`, **zero** `closing` (so none after the `closed`), end state `CLOSED`. It fails
without the guard (unguarded `else` would append `closing` after `closed`).

## 4. Verification

- `uv run --extra dev pytest tests/test_cohort_close_drain.py` → **7 passed** (6 prior + the new ordering test).
- `uv run --extra dev pytest` (full agent-runtime) → **365 passed, 4 skipped** (was 364/4; +1 new test, no
  regressions).

## 5. Confirmation — exactly-one-`closed` and the drain unchanged

- No change to `begin_close`, `finalize_if_drained`, or `on_member_terminal`.
- Non-regression cases still hold (verified in the same file): close with 0 active → single `closed`, no
  `closing`; close with ≥1 active draining normally → `closing` then a single `closed`; duplicate close →
  idempotent no-op; no-cohort close → no-op; the original concurrent race → exactly one `closed`, final `CLOSED`.
- Only `agent-runtime/app/services/cohort_service.py` (the guard + a docstring line) and its test changed. No
  new op, routing key, or state; no `begin_close`/`finalize_if_drained`/drain edits.
