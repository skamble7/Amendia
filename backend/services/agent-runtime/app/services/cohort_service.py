# app/services/cohort_service.py
"""ADR-063 Phase 1 — the thin cohort service: wraps the SoR repo + the fail-soft lifecycle emit.

Purely observational. ``join_on_spawn`` opens/joins a cohort by the trigger's business key and emits the
``opened``/``member_joined``/``late_join`` transitions; ``on_member_terminal`` drains the roster. It has NO
execution authority and — by contract with the caller — never raises into the dispatch/execution path
(callers still wrap it fail-soft, but it also swallows nothing that would corrupt the segment).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from amendia_contracts.dispatch import Trace

from app.dal.cohort_repo import CohortInstanceRepository
from app.events.publisher import emit_cohort_lifecycle
from app.models.cohort_instance import CohortInstance, CohortState

logger = logging.getLogger(__name__)


def resolve_correlation_value(envelope: Any, correlation_key: str) -> Optional[str]:
    """Resolve the cohort tie value from the trigger envelope via a dotpath (``a.b.c``). Returns the value as
    a string, or None when the field is absent/null/empty (→ graceful non-membership) or the envelope isn't a
    traversable object."""
    node: Any = envelope
    for part in correlation_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if node is None or node == "":
        return None
    return str(node)


class CohortService:
    def __init__(self, *, repo: CohortInstanceRepository, publisher) -> None:
        self._repo = repo
        self._publisher = publisher

    async def join_on_spawn(self, instance, membership, envelope: Any) -> Optional[CohortInstance]:
        """Join ``instance`` to its cohort. Returns the cohort it joined (opened or existing), or None when the
        trigger carries no correlation value (standalone segment). Emits ``opened`` on first create,
        ``member_joined`` on a fresh join, and ``late_join`` for the two anomalies (closed cohort; cohort_def_id
        mismatch — never re-homed, since ``correlation_value`` is the unique key). Idempotent on
        ``process_instance_id`` (a re-spawn adds nothing and emits nothing)."""
        correlation_value = resolve_correlation_value(envelope, membership.correlation_key)
        if correlation_value is None:
            logger.debug("cohort: correlation_key '%s' absent in trigger for %s — runs standalone",
                         membership.correlation_key, instance.process_instance_id)
            return None

        cohort, created = await self._repo.get_or_open(correlation_value, membership.cohort_def_id)
        coh_id = cohort.cohort_instance_id
        # trace_id is unknown here — the instance root span opens later in engine.start; carry correlation_id.
        trace = Trace(correlation_id=instance.correlation_id)

        if created:
            await emit_cohort_lifecycle(
                self._publisher, op="opened", cohort_def_id=cohort.cohort_def_id,
                cohort_instance_id=coh_id, correlation_value=correlation_value, trace=trace)

        def_mismatch = cohort.cohort_def_id != membership.cohort_def_id
        is_closed = cohort.state == CohortState.CLOSED

        added = await self._repo.add_member(coh_id, instance.process_instance_id, instance.pack_key)
        if not added:
            return cohort  # idempotent re-join (checkpoint replay) — already on the roster, no event

        if def_mismatch or is_closed:
            detail = (f"cohort_def_id mismatch: cohort={cohort.cohort_def_id} membership={membership.cohort_def_id}"
                      if def_mismatch else "member joined after cohort was closed")
            logger.warning("cohort %s late_join by %s: %s", coh_id, instance.process_instance_id, detail)
            await emit_cohort_lifecycle(
                self._publisher, op="late_join", cohort_def_id=cohort.cohort_def_id,
                cohort_instance_id=coh_id, correlation_value=correlation_value,
                process_instance_id=instance.process_instance_id, pack_key=instance.pack_key,
                pack_version=instance.pack_version, detail=detail, trace=trace)
        else:
            await emit_cohort_lifecycle(
                self._publisher, op="member_joined", cohort_def_id=cohort.cohort_def_id,
                cohort_instance_id=coh_id, correlation_value=correlation_value,
                process_instance_id=instance.process_instance_id, pack_key=instance.pack_key,
                pack_version=instance.pack_version, trace=trace)
        return cohort

    async def on_member_terminal(self, instance) -> None:
        """Drain hook: a member reached a terminal state → mark it terminal + decrement the active count. If the
        cohort is `closing` and this was the last active member, finalize `closing → closed` via the shared
        atomic conditional and emit `closed`. Idempotent; member-terminal itself emits no lifecycle event."""
        coh_id = getattr(instance, "cohort_instance_id", None)
        if not coh_id:
            return
        updated = await self._repo.mark_member_terminal(coh_id, instance.process_instance_id)
        if updated is None:
            return  # already terminal / unknown member — nothing to drain
        if updated.state == CohortState.CLOSING and updated.active_member_count == 0:
            finalized = await self._repo.finalize_if_drained(coh_id)
            if finalized is not None:                      # we won the single atomic finalize → emit closed once
                await self._emit_closed(finalized)

    async def close(self, correlation_value: str, close_outcome: Optional[str] = None) -> None:
        """ADR-063 Phase 2: drive the cohort's close by `correlation_value` alone (the sole handle). No cohort for
        the value → benign no-op. Otherwise `begin_close` (atomic `open → closing`, idempotent on duplicate
        close), then immediately attempt the shared `finalize_if_drained`: if no member was in flight it goes
        straight to `closed` (emit `closed`); otherwise it stays `closing` (emit `closing`) and the member-drain
        finalizes later. If a concurrent last-member drain already finalized in the begin_close→finalize gap,
        this emits nothing (the drain emitted the single `closed`) — never `closing` after `closed`. Close never
        terminates a segment."""
        existing = await self._repo.get_by_correlation_value(correlation_value)
        if existing is None:
            logger.info("cohort close: no cohort for correlation_value=%s — benign no-op", correlation_value)
            return
        closing = await self._repo.begin_close(correlation_value, close_outcome)
        if closing is None:
            logger.info("cohort close: %s already closing/closed — idempotent no-op", correlation_value)
            return
        finalized = await self._repo.finalize_if_drained(closing.cohort_instance_id)
        if finalized is not None:
            await self._emit_closed(finalized)             # no member in flight → open → closed directly
            return
        # finalize matched nothing → EITHER members are still running (legitimately `closing`) OR a concurrent
        # last-member drain already finalized to `closed` in the begin_close→finalize gap. Only the former should
        # emit `closing`; re-read to disambiguate so the stream never carries `closing` AFTER `closed`.
        current = await self._repo.get(closing.cohort_instance_id)
        if current is not None and current.state == CohortState.CLOSING:
            await emit_cohort_lifecycle(
                self._publisher, op="closing", cohort_def_id=closing.cohort_def_id,
                cohort_instance_id=closing.cohort_instance_id, correlation_value=closing.correlation_value,
                close_outcome=close_outcome,
                detail=(f"close_outcome={close_outcome}" if close_outcome else None))
        # else: a concurrent drain already finalized → `closed` was emitted there; stay silent.

    async def _emit_closed(self, cohort: CohortInstance) -> None:
        await emit_cohort_lifecycle(
            self._publisher, op="closed", cohort_def_id=cohort.cohort_def_id,
            cohort_instance_id=cohort.cohort_instance_id, correlation_value=cohort.correlation_value,
            close_outcome=cohort.close_outcome,
            detail=(f"close_outcome={cohort.close_outcome}" if cohort.close_outcome else None))
