# Claude Code prompt — ADR-063 fix: suppress the stray `closing`-after-`closed` cohort event

A **tiny, surgical** fix on top of ADR-063 Phase 2. No new behaviour, no scope beyond the one race below. The
exactly-one-`closed` guarantee is already correct and must stay correct — this only stops a spurious `closing`
event from being emitted **after** a cohort has already gone `closed`.

## The bug (confirmed by reading the code)

In `backend/services/agent-runtime/app/services/cohort_service.py`, `CohortService.close()` has an `await` gap
between `begin_close` (→ `CLOSING`) and its own `finalize_if_drained`. Under this interleaving with the last
active member terminating:

1. `close()` → `begin_close` sets state `CLOSING` (`active_member_count = 1`).
2. Before `close()` reaches `finalize_if_drained`, that last member terminates → `on_member_terminal`
   decrements `active → 0`, matches `{state: CLOSING, active_member_count: 0}`, wins `finalize_if_drained` →
   state `CLOSED`, emits **`closed`**.
3. Back in `close()`, `finalize_if_drained` now matches nothing (state is `CLOSED`) → returns `None` → the
   current `else` branch **unconditionally emits `closing`**.

Result: the lifecycle stream can carry `closed` **then** `closing`. State is correct (`CLOSED`) and `closed` is
emitted exactly once — but the trailing `closing` is dishonest and would make a naive Phase-3 projection read a
cohort flipping closed→closing.

Root cause: a `None` from `finalize_if_drained` conflates two cases — "members still running (legitimately
`closing`)" vs "a concurrent drain already finalized to `closed`". Only the first should emit `closing`.

## The fix

In `CohortService.close()`, guard the `else` branch so it emits `closing` **only when the cohort is still
`CLOSING`**. When a concurrent drain already finalized it to `CLOSED`, emit nothing (the drain already emitted
`closed`):

```python
finalized = await self._repo.finalize_if_drained(closing.cohort_instance_id)
if finalized is not None:
    await self._emit_closed(finalized)               # no member in flight → open → closed directly
else:
    current = await self._repo.get(closing.cohort_instance_id)
    if current is not None and current.state == CohortState.CLOSING:
        await emit_cohort_lifecycle(
            self._publisher, op="closing", cohort_def_id=closing.cohort_def_id,
            cohort_instance_id=closing.cohort_instance_id, correlation_value=closing.correlation_value,
            detail=(f"close_outcome={close_outcome}" if close_outcome else None))
    # else: a concurrent drain already finalized → `closed` was emitted there; stay silent
```

`CohortInstanceRepository.get(cohort_instance_id)` already exists (used elsewhere) — reuse it; do not add a
repo method.

**Preferred, fully-atomic alternative (do this if it's clean, else the re-read above is acceptable):** make
`finalize_if_drained` — or a small sibling the caller uses — return a **tri-state** distinguishing *finalized*
/ *still-closing* / *already-closed* from a single `find_one_and_update`/read, so `close()` needs no separate
re-read (removes the small TOCTOU between the failed finalize and the re-read). If you take this path, keep the
signature change local to `close()`'s call site; `on_member_terminal`'s use of `finalize_if_drained` must be
unaffected.

## Do not

- Do not change the atomic `begin_close` / `finalize_if_drained` conditionals or the drain in
  `on_member_terminal` — the exactly-one-`closed` behaviour is correct and must not regress.
- Do not emit any new op, change routing keys, or touch the `open → closing → closed` states.
- Do not alter Phase 1/2 behaviour beyond suppressing the spurious trailing `closing`.
- No git writes — leave the tree dirty; the operator owns commits.

## Tests

- **New race test** (mirror `test_close_racing_last_member_yields_exactly_one_closed`, but assert **ordering**):
  drive the interleaving where the last member finalizes in the `begin_close`→`finalize` window, then assert the
  emitted lifecycle ops contain exactly one `closed`, **zero** `closing` after that `closed`, and end state
  `CLOSED`. (Deterministically force the interleave — e.g. await the member drain to completion between
  `begin_close` and `close()`'s finalize, or patch the repo to yield — rather than relying on scheduler luck.)
- **Non-regression:** the existing cases still hold — close with 0 active → single `closed`, no `closing`;
  close with ≥1 active that drains normally → `closing` then a single `closed`; duplicate close → idempotent
  no-op; no-cohort close → no-op.

## Acceptance

- After a `close()` whose finalize loses to a concurrent last-member drain, **no** `closing` event is emitted
  (only the drain's single `closed`); the "members still running" path still emits `closing` exactly once.
- Exactly-one-`closed` preserved in every interleaving; final state always `CLOSED`.
- `pytest` green for `agent-runtime`; all existing ADR-063 cohort tests unaffected.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR063_close_event_ordering_guard_report.md`
(uncommitted): (1) outcome one-liner; (2) which approach you took (re-read guard vs tri-state) and why; (3) the
new ordering test + how the interleave is forced deterministically; (4) verification commands + results; (5)
confirmation that exactly-one-`closed` and the drain are unchanged. A few lines is fine — this is a small fix.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Smallest correct change; stay inside
`agent-runtime` `cohort_service.py` (+ its test, and `cohort_repo.py` only if you take the tri-state option).
