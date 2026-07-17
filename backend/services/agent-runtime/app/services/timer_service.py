# app/services/timer_service.py
"""TimerService — durable timers with an injectable clock (ADR-027 Phase 2.2).

Thin domain wrapper over :class:`TimerRepository`. The ONLY place real wall-clock time is read is
``now()`` (default real UTC); tests inject a controllable clock and drive firing through the
engine's ``fire_due(now)`` seam — so every timer test is deterministic with no ``sleep``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from amendia_bpmn import TimerDef, parse_timer

from app.dal.timer_repo import TimerRepository
from app.models.timer import Timer, TimerKind, TimerStatus


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimerService:
    def __init__(self, repo: TimerRepository, *, now: Callable[[], datetime] = _real_utc_now) -> None:
        self._repo = repo
        self._now = now

    def now(self) -> datetime:
        return self._now()

    def fire_at(self, timer: TimerDef, *, base_now: Optional[datetime] = None) -> datetime:
        """Resolve a BPMN timer definition to a concrete instant relative to the injected clock."""
        return parse_timer(timer, base_now or self._now())

    async def register(
        self, *, process_instance_id: str, element_id: str, kind: TimerKind, fire_at: datetime,
        interrupt_id: Optional[str] = None, task_id: Optional[str] = None,
        gateway_id: Optional[str] = None,
        pack_key: Optional[str] = None, pack_version: Optional[str] = None,
    ) -> Timer:
        timer = Timer(
            timer_id=f"tmr-{uuid.uuid4().hex[:12]}",
            process_instance_id=process_instance_id, element_id=element_id, kind=kind,
            fire_at=fire_at, interrupt_id=interrupt_id, task_id=task_id, gateway_id=gateway_id,
            pack_key=pack_key, pack_version=pack_version,
        )
        return await self._repo.register(timer)

    async def due(self, now: Optional[datetime] = None) -> List[Timer]:
        return await self._repo.due(now or self._now())

    async def mark_fired(self, timer_id: str) -> Optional[Timer]:
        return await self._repo.mark(timer_id, TimerStatus.FIRED)

    async def cancel_by_interrupt(self, process_instance_id: str, interrupt_id: Optional[str]) -> int:
        return await self._repo.cancel_by_interrupt(process_instance_id, interrupt_id)

    async def cancel_for_instance(self, process_instance_id: str) -> int:
        return await self._repo.cancel_for_instance(process_instance_id)

    async def cancel_gateway_arms(self, process_instance_id: str, *, keep_element_id: str) -> int:
        return await self._repo.cancel_gateway_arms(process_instance_id, keep_element_id=keep_element_id)

    async def list_for_instance(self, process_instance_id: str) -> List[Timer]:
        return await self._repo.list_for_instance(process_instance_id)
