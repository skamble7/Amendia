# app/services/hitl_service.py
"""HITL decision service: claim, decide, resume.

Enforces the lifecycle (open → claimed → decided), SoD exclusions (checked at
claim AND decide), the allowed-decisions table, and ``edit_and_approve`` schema
re-validation. On a valid decision it persists the DecisionRecord, publishes
``hitl_task_decided``, and resumes the graph on the instance's thread.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator

from amendia_contracts.hitl_task import Decision, HitlTaskDecidedEvent, TaskStatus

from app.engine.engine import ProcessEngine
from app.logging_conf import exception_id_ctx

logger = logging.getLogger(__name__)


class HitlError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HitlDecisionService:
    def __init__(self, *, hitl_repo, instance_repo, engine: ProcessEngine, publisher) -> None:
        self._hitl = hitl_repo
        self._instances = instance_repo
        self._engine = engine
        self._publisher = publisher

    async def claim(self, task_id: str, *, actor_id: str, actor_roles: set[str]):
        """Claim a task. Identity + roles come from the authenticated caller
        (token → identity service), never from the request body. Enforces the
        task's required role ∈ the actor's roles, plus SoD by amendia_user_id."""
        task = await self._hitl.get(task_id)
        if task is None:
            raise HitlError(404, f"no hitl task {task_id}")
        if task.status is not TaskStatus.OPEN:
            raise HitlError(409, f"task is '{task.status.value}', not open")
        self._check_sod(task, actor_id)
        if task.role not in actor_roles:
            raise HitlError(403, f"caller lacks required role '{task.role}'")
        updated = await self._hitl.transition_status(
            task_id, expected_status=TaskStatus.OPEN, new_status=TaskStatus.CLAIMED,
            set_fields={"assignee": actor_id},
        )
        if updated is None:
            raise HitlError(409, "task was claimed concurrently")
        logger.info("hitl task %s claimed by %s", task_id, actor_id)
        return updated

    async def decide(
        self, task_id: str, *, actor_id: str, decision: str,
        comment: Optional[str] = None, edits: Optional[Dict[str, Any]] = None,
        approved_action_ids: Optional[List[str]] = None,
    ):
        task = await self._hitl.get(task_id)
        if task is None:
            raise HitlError(404, f"no hitl task {task_id}")
        if task.status is not TaskStatus.CLAIMED:
            raise HitlError(409, f"task is '{task.status.value}', not claimed")
        if task.assignee != actor_id:
            raise HitlError(409, f"task claimed by '{task.assignee}', not '{actor_id}'")
        self._check_sod(task, actor_id)

        try:
            decision_enum = Decision(decision)
        except ValueError:
            raise HitlError(400, f"unknown decision '{decision}'")
        if decision_enum not in task.allowed_decisions:
            allowed = [d.value for d in task.allowed_decisions]
            raise HitlError(400, f"decision '{decision}' not allowed (allowed: {allowed})")

        if decision_enum is Decision.EDIT_AND_APPROVE:
            err = await self._validate_edits(task, edits)
            if err:
                raise HitlError(400, f"edits invalid: {err}")

        record = {
            "decision": decision_enum.value,
            "decided_by": actor_id,
            "decided_at": _now_iso(),
            "comment": comment,
            "edits": edits,
            "approved_action_ids": approved_action_ids,
        }
        updated = await self._hitl.transition_status(
            task_id, expected_status=TaskStatus.CLAIMED, new_status=TaskStatus.DECIDED,
            set_fields={"decision": record},
        )
        if updated is None:
            raise HitlError(409, "task was decided concurrently")

        token = exception_id_ctx.set(task.exception_id)
        try:
            await self._publish_decided(task, decision_enum, actor_id)
            payload = {
                "decision": decision_enum.value, "decided_by": actor_id,
                "edits": edits, "approved_action_ids": approved_action_ids, "comment": comment,
            }
            logger.info("hitl task %s decided '%s' by %s → resuming instance %s",
                        task_id, decision, actor_id, task.process_instance_id)
            await self._engine.resume(task.process_instance_id, payload, interrupt_id=task.interrupt_id)
        finally:
            exception_id_ctx.reset(token)
        return updated

    # ------------------------------------------------------------------ #
    def _check_sod(self, task, user_id: str) -> None:
        if task.sod and task.sod.excluded_users and user_id in task.sod.excluded_users:
            raise HitlError(403, f"user '{user_id}' is excluded by separation-of-duties")

    async def _validate_edits(self, task, edits: Optional[Dict[str, Any]]) -> Optional[str]:
        if not isinstance(edits, dict):
            return "edits must be an object"
        specs = await self._engine.output_specs(task.pack_key, task.pack_version, task.element_id)
        if not specs:
            return "this task produces no editable output"
        for spec in specs:
            data = edits.get(spec.name, edits.get(spec.artifact_key))
            if data is None:
                return f"missing edited artifact '{spec.name}'"
            errors = sorted(Draft202012Validator(spec.json_schema).iter_errors(data), key=lambda e: e.path)
            if errors:
                e = errors[0]
                loc = "/".join(str(p) for p in e.path)
                return f"{spec.schema_ref} at '{loc or '<root>'}': {e.message}"
        return None

    async def _publish_decided(self, task, decision_enum: Decision, user_id: str) -> None:
        if self._publisher is None:
            return
        event = HitlTaskDecidedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            task_id=task.task_id, exception_id=task.exception_id,
            process_instance_id=task.process_instance_id, element_id=task.element_id,
            role=task.role, decision=decision_enum, decided_by=user_id,
        )
        await self._publisher.publish(event.to_doc(), event.routing_key(), event.event_id)
