# app/engine/engine.py
"""ProcessEngine — the async orchestrator around the compiled LangGraph graphs.

Responsibilities:
  * load + cache pack bundles (from the registry) and compiled graphs, keyed by
    (pack_key, pack_version) — packs are immutable once active, so cache forever;
  * run/resume graph *segments* (a bounded computation ending at the next HITL
    interrupt or at END) in a worker thread (the Mongo checkpointer is sync);
  * materialize a ``HitlTask`` from each interrupt payload, set the instance to
    ``waiting_hitl``, publish ``hitl_task_created``;
  * on END, mark the instance ``completed``/``failed`` and publish the lifecycle
    event;
  * recover ``running`` instances on startup by re-invoking their thread.

Graph nodes are synchronous and pure; all IO (Mongo, Rabbit, registry) lives
here in the async layer.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from langgraph.types import Command
from pymongo import MongoClient as PyMongoClient

try:  # langgraph-checkpoint-mongodb
    from langgraph.checkpoint.mongodb import MongoDBSaver
except Exception:  # pragma: no cover
    MongoDBSaver = None  # type: ignore

from amendia_bpmn import parse
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.dispatch import Trace
from amendia_contracts.hitl_task import HitlTask, HitlTaskCreatedEvent
from amendia_contracts.process_events import ProcessCompletedEvent, ProcessFailedEvent
from amendia_contracts.process_pack import ProcessPackManifest

from app.clients.registry_client import RegistryClient, RegistryNotFound
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.compiler import FAILED_OUTCOME, compile_graph
from app.engine.executor import Executor
from app.engine.hitl import allowed_decisions_for, compute_sod_excluded
from app.engine.state import initial_state
from app.models.process_instance import InstanceStatus, ProcessInstance

logger = logging.getLogger(__name__)


class PackNotActive(Exception):
    def __init__(self, pack_key: str, version: str, status: str) -> None:
        self.pack_key, self.version, self.status = pack_key, version, status
        super().__init__(f"pack {pack_key}@{version} is '{status}', not active")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessEngine:
    def __init__(
        self,
        *,
        registry: RegistryClient,
        instance_repo,
        hitl_repo,
        publisher,
        settings,
        executor: Optional[Executor] = None,
        checkpointer: Any = None,
    ) -> None:
        self._registry = registry
        self._instances = instance_repo
        self._hitl = hitl_repo
        self._publisher = publisher
        self._settings = settings
        self._executor = executor or Executor()
        self._bundles: Dict[Tuple[str, str], PackBundle] = {}
        self._graphs: Dict[Tuple[str, str], Any] = {}
        self._lock = asyncio.Lock()
        self._checkpointer = checkpointer or self._make_checkpointer(settings)

    @staticmethod
    def _make_checkpointer(settings):
        if MongoDBSaver is None:  # pragma: no cover
            raise RuntimeError("langgraph-checkpoint-mongodb is not installed")
        client = PyMongoClient(settings.MONGO_URI)
        return MongoDBSaver(
            client,
            db_name=settings.MONGO_DB,
            checkpoint_collection_name=settings.CHECKPOINT_COLLECTION,
            writes_collection_name=settings.CHECKPOINT_WRITES_COLLECTION,
        )

    # ------------------------------------------------------------------ #
    # Bundle / graph loading + caching
    # ------------------------------------------------------------------ #
    async def load_bundle(self, pack_key: str, version: str) -> PackBundle:
        key = (pack_key, version)
        if key in self._bundles:
            return self._bundles[key]
        async with self._lock:
            if key in self._bundles:
                return self._bundles[key]
            bundle = await self._fetch_bundle(pack_key, version)
            self._bundles[key] = bundle
            return bundle

    async def _fetch_bundle(self, pack_key: str, version: str) -> PackBundle:
        try:
            manifest_doc = await self._registry.get_pack(pack_key, version)
        except RegistryNotFound as exc:
            raise RegistryNotFound(f"pack {pack_key}@{version}") from exc
        status = manifest_doc.get("status")
        if status != "active":
            raise PackNotActive(pack_key, version, str(status))
        manifest = ProcessPackManifest.model_validate(manifest_doc)

        resolution = await self._registry.get_resolution(pack_key, version)
        bpmn_xml = await self._registry.get_bpmn(pack_key, version)
        bpmn_model, findings = parse(bpmn_xml, manifest.process.process_id)
        if findings:
            raise ValueError(f"pack BPMN did not parse: {[f.code for f in findings]}")

        descriptors: Dict[str, CapabilityDescriptor] = {}
        for cid, ver in resolution.get("capabilities", {}).items():
            descriptors[cid] = CapabilityDescriptor.model_validate(
                await self._registry.get_capability(cid, ver)
            )
        schemas: Dict[str, Dict[str, Any]] = {}
        for akey, ver in resolution.get("artifacts", {}).items():
            reg = await self._registry.get_artifact_schema(akey, ver)
            schemas[f"{akey}@{ver}"] = reg["json_schema"]

        return PackBundle(
            manifest=manifest, resolution=resolution, bpmn_model=bpmn_model,
            descriptors=descriptors, schemas=schemas, bpmn_xml=bpmn_xml,
        )

    async def get_graph(self, pack_key: str, version: str):
        key = (pack_key, version)
        if key in self._graphs:
            return self._graphs[key]
        bundle = await self.load_bundle(pack_key, version)
        async with self._lock:
            if key in self._graphs:
                return self._graphs[key]
            graph = compile_graph(
                bundle, self._executor,
                simulation=self._settings.SIMULATION_MODE, checkpointer=self._checkpointer,
            )
            self._graphs[key] = graph
            return graph

    def cached_bundle(self, pack_key: str, version: str) -> Optional[PackBundle]:
        return self._bundles.get((pack_key, version))

    async def output_specs(self, pack_key: str, version: str, element_id: str):
        """Pinned output specs for an element (used to validate ``edit_and_approve``)."""
        bundle = await self.load_bundle(pack_key, version)
        ctxs = build_node_contexts(bundle)
        ctx = ctxs.get(element_id)
        return ctx.outputs if ctx else []

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #
    async def start(self, instance: ProcessInstance, envelope: Dict[str, Any]) -> None:
        graph = await self.get_graph(instance.pack_key, instance.pack_version)
        trace = {"correlation_id": instance.correlation_id, "causation_id": None}
        init = initial_state(
            envelope=envelope, trace=trace,
            pack={"pack_key": instance.pack_key, "pack_version": instance.pack_version},
        )
        await self._instances.set_status(
            instance.process_instance_id, InstanceStatus.RUNNING, expected=[InstanceStatus.CREATED]
        )
        logger.info("instance %s running (correlation_id=%s)",
                    instance.process_instance_id, instance.correlation_id)
        await self._run_segment(instance, graph, init)

    async def resume(self, process_instance_id: str, decision_payload: Dict[str, Any]) -> None:
        instance = await self._instances.get(process_instance_id)
        if instance is None:
            raise KeyError(f"no instance {process_instance_id}")
        graph = await self.get_graph(instance.pack_key, instance.pack_version)
        await self._instances.set_status(
            process_instance_id, InstanceStatus.RUNNING, expected=[InstanceStatus.WAITING_HITL]
        )
        await self._run_segment(instance, graph, Command(resume=decision_payload))

    async def recover(self) -> int:
        """Startup sweep: re-invoke instances left ``running`` at last checkpoint."""
        running = await self._instances.list_by_status(InstanceStatus.RUNNING)
        for inst in running:
            try:
                graph = await self.get_graph(inst.pack_key, inst.pack_version)
                logger.info("recovering running instance %s", inst.process_instance_id)
                await self._run_segment(inst, graph, None)
            except Exception as exc:  # noqa: BLE001
                logger.exception("recovery failed for %s: %s", inst.process_instance_id, exc)
        return len(running)

    async def _run_segment(self, instance: ProcessInstance, graph, cmd_or_input) -> None:
        cfg = {"configurable": {"thread_id": instance.process_instance_id}}
        try:
            result = await asyncio.to_thread(graph.invoke, cmd_or_input, cfg)
        except Exception as exc:  # noqa: BLE001 - any node failure terminates the instance
            reason = getattr(exc, "reason", "node_error")
            logger.exception("instance %s failed in a node: %s", instance.process_instance_id, exc)
            await self._fail(instance, reason, str(exc))
            return

        if isinstance(result, dict) and "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            state = await asyncio.to_thread(lambda: graph.get_state(cfg).values)
            await self._materialize_task(instance, payload, state)
        else:
            await self._complete(instance, result)

    # ------------------------------------------------------------------ #
    # HITL task materialization
    # ------------------------------------------------------------------ #
    async def _materialize_task(self, instance: ProcessInstance, payload: Dict[str, Any], state: Dict[str, Any]) -> None:
        bundle = self.cached_bundle(instance.pack_key, instance.pack_version)
        sod_policies = []
        if bundle and bundle.manifest.policies and bundle.manifest.policies.separation_of_duties:
            sod_policies = bundle.manifest.policies.separation_of_duties
        excluded, derived = compute_sod_excluded(
            sod_policies, state.get("actor_log", []), payload["element_id"]
        )

        mode = payload["hitl_mode"]
        task_id = f"hitl-{uuid.uuid4().hex[:12]}"
        pid = instance.process_instance_id
        artifacts = [
            {"name": a["name"], "schema": a["schema"], "data": a.get("data")}
            for a in payload.get("artifacts", [])
        ]
        task_doc = {
            "task_id": task_id,
            "process_instance_id": pid,
            "pack_key": instance.pack_key,
            "pack_version": instance.pack_version,
            "element_id": payload["element_id"],
            "exception_id": instance.exception_id,
            "hitl_mode": mode,
            "role": payload["role"],
            "title": payload.get("title") or payload["element_id"],
            "priority": "normal",
            "sod": {"excluded_users": excluded, "derived_from": derived},
            "payload": {
                "artifacts": artifacts,
                "proposed_actions": payload.get("proposed_actions") or None,
                "context_url": f"{self._settings.SELF_BASE_URL.rstrip('/')}/instances/{pid}",
            },
            "allowed_decisions": [d.value for d in allowed_decisions_for(mode)],
            "status": "open",
        }
        task = HitlTask.model_validate(task_doc)
        await self._hitl.insert(task)
        await self._instances.set_status(
            pid, InstanceStatus.WAITING_HITL,
            expected=[InstanceStatus.RUNNING, InstanceStatus.CREATED],
        )
        logger.info("instance %s waiting_hitl: task %s element=%s mode=%s excluded=%s",
                    pid, task_id, payload["element_id"], mode, excluded)
        await self._publish(HitlTaskCreatedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            task_id=task_id, exception_id=instance.exception_id, process_instance_id=pid,
            element_id=payload["element_id"], role=payload["role"],
        ))

    # ------------------------------------------------------------------ #
    # Terminal states
    # ------------------------------------------------------------------ #
    async def _complete(self, instance: ProcessInstance, result: Dict[str, Any]) -> None:
        outcome = (result or {}).get("outcome")
        if outcome == FAILED_OUTCOME:
            await self._fail(instance, "route_failed", (result or {}).get("last_error"))
            return
        artifact_names = sorted((result or {}).get("artifacts", {}).keys())
        await self._instances.set_status(
            instance.process_instance_id, InstanceStatus.COMPLETED,
            outcome=outcome, artifact_names=artifact_names,
        )
        logger.info("instance %s completed outcome=%s artifacts=%s",
                    instance.process_instance_id, outcome, artifact_names)
        await self._publish(ProcessCompletedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            process_instance_id=instance.process_instance_id, exception_id=instance.exception_id,
            pack_key=instance.pack_key, pack_version=instance.pack_version,
            outcome=outcome or "unknown",
            trace=Trace(correlation_id=instance.correlation_id),
        ))

    async def _fail(self, instance: ProcessInstance, reason: str, detail: Optional[str]) -> None:
        await self._instances.set_status(
            instance.process_instance_id, InstanceStatus.FAILED,
            outcome=FAILED_OUTCOME, last_error=detail,
        )
        logger.warning("instance %s failed reason=%s detail=%s",
                       instance.process_instance_id, reason, detail)
        await self._publish(ProcessFailedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            process_instance_id=instance.process_instance_id, exception_id=instance.exception_id,
            pack_key=instance.pack_key, pack_version=instance.pack_version,
            reason=reason, detail=detail, trace=Trace(correlation_id=instance.correlation_id),
        ))

    # ------------------------------------------------------------------ #
    async def get_checkpoint_state(self, process_instance_id: str, pack_key: str, pack_version: str) -> Dict[str, Any]:
        graph = await self.get_graph(pack_key, pack_version)
        cfg = {"configurable": {"thread_id": process_instance_id}}
        snapshot = await asyncio.to_thread(lambda: graph.get_state(cfg))
        return snapshot.values if snapshot else {}

    async def _publish(self, event) -> None:
        if self._publisher is None:
            return
        try:
            await self._publisher.publish(event.to_doc(), event.routing_key(), event.event_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to publish %s: %s", type(event).__name__, exc)
