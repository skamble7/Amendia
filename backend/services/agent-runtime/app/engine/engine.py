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

from amendia_bpmn import parse, profile_rank
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.dispatch import Trace
from amendia_contracts.hitl_task import (
    HitlTask,
    HitlTaskCreatedEvent,
    HitlTaskExpiredEvent,
    TaskStatus,
)
from amendia_contracts.process_events import (
    MessageReceivedEvent,
    ProcessCompletedEvent,
    ProcessFailedEvent,
    TimerFiredEvent,
)
from jsonschema import Draft202012Validator
from amendia_contracts.process_pack import ProcessPackManifest

from app.clients.registry_client import RegistryClient, RegistryNotFound
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.compiler import FAILED_OUTCOME, compile_graph
from app.engine.executor import Executor, InProcessExecutor
from app.engine.hitl import allowed_decisions_for, compute_sod_excluded
from app.engine.state import initial_state
from app.models.message import SubscriptionKind
from app.models.process_instance import InstanceStatus, ProcessInstance
from app.models.timer import Timer, TimerKind

logger = logging.getLogger(__name__)


class PackNotActive(Exception):
    def __init__(self, pack_key: str, version: str, status: str) -> None:
        self.pack_key, self.version, self.status = pack_key, version, status
        super().__init__(f"pack {pack_key}@{version} is '{status}', not active")


class PackRequiresProfile(Exception):
    """ADR-027 Phase 2.5: this runtime's execution profile is lower-ranked than the pack needs.

    Raised at *load* (not mid-flight) so dispatch can refuse cleanly with a distinct reason,
    rather than the pack surfacing later as an opaque CompilerError during execution.
    """

    def __init__(self, pack_key: str, version: str, required: str, runtime: str) -> None:
        self.pack_key, self.version = pack_key, version
        self.required, self.runtime = required, runtime
        super().__init__(
            f"pack {pack_key}@{version} requires execution profile '{required}' but this "
            f"runtime is '{runtime}'"
        )


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
        timer_service: Any = None,
        message_service: Any = None,
    ) -> None:
        self._registry = registry
        self._instances = instance_repo
        self._hitl = hitl_repo
        self._publisher = publisher
        self._settings = settings
        self._executor = executor or InProcessExecutor()
        # ADR-027 Phase 2.2: durable timers. Optional — when absent (unit tests without the substrate)
        # timer constructs simply aren't scheduled; packs needing them require the "timers" profile.
        self._timers = timer_service
        # ADR-031 Phase 2.4: message subscriptions (+ ordering buffer). Optional, same rationale.
        self._messages = message_service
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
        # ADR-027 Phase 2.5: refuse a pack this runtime can't execute at LOAD, not mid-flight.
        # Profiles are a hierarchy checked with >=: a runtime at rank X runs any pack needing rank
        # ≤ X. Older packs with no pin default to the conservative common_subset.
        runtime_profile = getattr(self._settings, "EXECUTION_PROFILE", "common_subset")
        required = resolution.get("required_execution_profile", "common_subset")
        if profile_rank(required) > profile_rank(runtime_profile):
            raise PackRequiresProfile(pack_key, version, required, runtime_profile)
        bpmn_xml = await self._registry.get_bpmn(pack_key, version)
        bpmn_model, findings = parse(bpmn_xml, manifest.process.process_id)
        # ADR-027: reject only on error-severity findings; documented/unknown are warning/info
        # and must not block loading an active pack whose diagram is richer than the subset.
        errors = [f for f in findings if f.severity == "error"]
        if errors:
            raise ValueError(f"pack BPMN did not parse: {[f.code for f in errors]}")

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
        # ADR-039: pre-fetch every pinned callActivity callee bundle (recursively) so the pure/sync
        # compiler can resolve them through an in-memory provider and inline-splice them.
        await self._prefetch_callees(bundle, set())

        def provider(pk: str, ver: str) -> PackBundle:
            b = self._bundles.get((pk, ver))
            if b is None:
                raise KeyError(f"callee bundle {pk}@{ver} was not prefetched")
            return b

        async with self._lock:
            if key in self._graphs:
                return self._graphs[key]
            graph = compile_graph(
                bundle, self._executor,
                simulation=self._settings.SIMULATION_MODE, checkpointer=self._checkpointer,
                profile=getattr(self._settings, "EXECUTION_PROFILE", "common_subset"),
                bundle_provider=provider,
            )
            self._graphs[key] = graph
            return graph

    async def _prefetch_callees(self, bundle: PackBundle, seen: set) -> None:
        """Recursively load a composite pack's pinned callee bundles into the bundle cache (ADR-039)."""
        for ca in bundle.resolution.get("call_activities", []) or []:
            pk, ver = ca.get("pack_key"), ca.get("version")
            if not pk or not ver or (pk, ver) in seen:
                continue
            seen.add((pk, ver))
            callee = await self.load_bundle(pk, ver)  # applies the PackNotActive / profile guards too
            await self._prefetch_callees(callee, seen)

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

    async def resume(self, process_instance_id: str, decision_payload: Dict[str, Any],
                     interrupt_id: Optional[str] = None) -> None:
        instance = await self._instances.get(process_instance_id)
        if instance is None:
            raise KeyError(f"no instance {process_instance_id}")
        graph = await self.get_graph(instance.pack_key, instance.pack_version)
        won = await self._instances.set_status(
            process_instance_id, InstanceStatus.RUNNING, expected=[InstanceStatus.WAITING_HITL]
        )
        if won is None:
            # ADR-027 Phase 2.2: the SLA timer fired first and already advanced this instance — the
            # human lost the race. (hitl_service also rejects the decision on the expired task.)
            logger.info("resume no-op for %s: instance not waiting_hitl (timer won the race?)",
                        process_instance_id)
            return
        # The human decided before the SLA timer: cancel this gate's boundary timer so the poller
        # won't later fire a stale escalation (the status guard already makes it safe; this is clean-up).
        if self._timers is not None:
            await self._timers.cancel_by_interrupt(process_instance_id, interrupt_id)
        # ADR-027 Phase 2.1: resume by interrupt id when known — the id-keyed form works for a lone
        # interrupt AND resolves exactly one of several concurrent ones (parallel branches). Bare
        # form is the legacy fallback for tasks materialized before interrupt ids were recorded.
        cmd = Command(resume={interrupt_id: decision_payload}) if interrupt_id else Command(resume=decision_payload)
        await self._run_segment(instance, graph, cmd)

    # ------------------------------------------------------------------ #
    # Timers (ADR-027 Phase 2.2)
    # ------------------------------------------------------------------ #
    async def fire_due(self, now=None) -> int:
        """Fire every timer due at ``now`` (the poller's tick; ``now`` overridable for deterministic
        tests). Each fire is guarded by the instance status transition, so a timer that lost the race
        to a human decision (or already fired) is a safe no-op."""
        if self._timers is None:
            return 0
        fired = 0
        for timer in await self._timers.due(now):
            try:
                if await self._fire_timer(timer):
                    fired += 1
            except Exception as exc:  # noqa: BLE001 - one bad timer must not stall the poller
                logger.exception("timer %s fire failed: %s", timer.timer_id, exc)
        return fired

    async def _fire_timer(self, timer: Timer) -> bool:
        instance = await self._instances.get(timer.process_instance_id)
        if instance is None:
            await self._timers.mark_fired(timer.timer_id)   # orphaned timer → resolve
            return False
        graph = await self.get_graph(instance.pack_key, instance.pack_version)
        intermediate = timer.kind == TimerKind.INTERMEDIATE
        # ADR-031: an event-gateway timer arm parks WAITING_MESSAGE (with its sibling message arms).
        gateway_arm = timer.gateway_id is not None
        if gateway_arm:
            expected = InstanceStatus.WAITING_MESSAGE
        else:
            expected = InstanceStatus.WAITING_TIMER if intermediate else InstanceStatus.WAITING_HITL
        # The single serialization point: whoever flips the parked instance to RUNNING wins.
        won = await self._instances.set_status(
            timer.process_instance_id, InstanceStatus.RUNNING, expected=[expected]
        )
        if won is None:
            await self._timers.mark_fired(timer.timer_id)   # human won, or already fired — stale
            return False
        if gateway_arm:
            # This timer arm won the event gateway — cancel the losing arms, resume the gateway node.
            await self._cancel_gateway_losers(instance, keep_element_id=timer.element_id)
            signal: Dict[str, Any] = {"arm": timer.element_id, "actor": "timer", "actor_kind": "timer"}
        elif intermediate:
            signal = {"kind": "timer_fired"}
        else:
            signal = {"__timeout__": True}
            await self._expire_task(instance, timer)         # SLA breach: expire the HITL task
        cmd = (Command(resume={timer.interrupt_id: signal}) if timer.interrupt_id
               else Command(resume=signal))
        await self._run_segment(instance, graph, cmd)
        await self._timers.mark_fired(timer.timer_id)
        if intermediate and not gateway_arm:
            await self._publish(TimerFiredEvent(
                event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
                process_instance_id=instance.process_instance_id, exception_id=instance.exception_id,
                element_id=timer.element_id, kind="intermediate",
                trace=Trace(correlation_id=instance.correlation_id),
            ))
        return True

    async def _expire_task(self, instance: ProcessInstance, timer: Timer) -> None:
        """Expire the HITL task the fired SLA boundary guarded (the human lost the race), then emit
        the escalation event. Guarded from open/claimed so a concurrent decide is the loser."""
        if not timer.task_id:
            return
        expired = None
        for st in (TaskStatus.OPEN, TaskStatus.CLAIMED):
            expired = await self._hitl.transition_status(
                timer.task_id, expected_status=st, new_status=TaskStatus.EXPIRED
            )
            if expired is not None:
                break
        if expired is None:
            return
        bundle = self.cached_bundle(instance.pack_key, instance.pack_version)
        boundary = (bundle.bpmn_model.boundary_timers.get(timer.element_id) if bundle else None)
        await self._publish(HitlTaskExpiredEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            task_id=timer.task_id, exception_id=instance.exception_id,
            process_instance_id=instance.process_instance_id, element_id=timer.element_id,
            role=expired.role, escalated_to=(boundary.target if boundary else None),
        ))
        logger.info("hitl task %s expired (SLA breach) → escalating to %s",
                    timer.task_id, boundary.target if boundary else "?")

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
            # ADR-027 Phase 2.1: a parallel superstep can raise SEVERAL concurrent interrupts.
            # Per the "sequentialize" decision, surface exactly ONE — materialize its task, park at
            # WAITING_HITL — and carry its interrupt id so resume targets this gate; the next
            # pending interrupt surfaces after this one is decided (one open HITL task at a time).
            interrupts = result["__interrupt__"]
            first = interrupts[0]
            if len(interrupts) > 1:
                logger.info("instance %s: %d concurrent interrupts — surfacing one at a time",
                            instance.process_instance_id, len(interrupts))
            payload = first.value
            kind = payload.get("kind") if isinstance(payload, dict) else None
            # ADR-027 Phase 2.2 / ADR-031 Phase 2.4: dispatch the interrupt by kind — a timer catch
            # parks WAITING_TIMER, a message catch/receive parks WAITING_MESSAGE, an event gateway
            # registers all arms and parks; anything else is a HITL gate.
            if kind == "timer":
                await self._park_timer(instance, payload, interrupt_id=first.id)
            elif kind == "message":
                await self._park_message(instance, payload, interrupt_id=first.id)
            elif kind == "event_gateway":
                await self._park_event_gateway(instance, payload, interrupt_id=first.id)
            else:
                state = await asyncio.to_thread(lambda: graph.get_state(cfg).values)
                await self._materialize_task(instance, payload, state, interrupt_id=first.id)
        else:
            await self._complete(instance, result)

    async def _park_timer(self, instance: ProcessInstance, payload: Dict[str, Any],
                          *, interrupt_id: Optional[str]) -> None:
        """Park an instance on a timer intermediate-catch: register a durable timer and set
        WAITING_TIMER. Idempotent — a crash-replay re-park upserts the same timer."""
        pid = instance.process_instance_id
        element_id = payload["element_id"]
        if self._timers is not None:
            bundle = self.cached_bundle(instance.pack_key, instance.pack_version)
            td = bundle.bpmn_model.timer_catch_events.get(element_id) if bundle else None
            fire_at = self._timers.fire_at(td) if td is not None else self._timers.now()
            await self._timers.register(
                process_instance_id=pid, element_id=element_id, kind=TimerKind.INTERMEDIATE,
                fire_at=fire_at, interrupt_id=interrupt_id,
                pack_key=instance.pack_key, pack_version=instance.pack_version,
            )
        await self._instances.set_status(
            pid, InstanceStatus.WAITING_TIMER,
            expected=[InstanceStatus.RUNNING, InstanceStatus.CREATED],
        )
        logger.info("instance %s waiting_timer: element=%s", pid, element_id)

    # ------------------------------------------------------------------ #
    # Messages (ADR-031 Phase 2.4)
    # ------------------------------------------------------------------ #
    def _arm_message_name(self, bundle, element_id: str) -> Optional[str]:
        b = next((b for b in bundle.manifest.bindings if b.element_id == element_id), None)
        return getattr(b.executor, "message_name", None) if b is not None else None

    async def _park_message(self, instance: ProcessInstance, payload: Dict[str, Any],
                            *, interrupt_id: Optional[str]) -> None:
        """Park an instance on a message catch / receive: register a subscription, set WAITING_MESSAGE,
        then check the ordering buffer for a message that arrived before we parked."""
        pid = instance.process_instance_id
        element_id = payload["element_id"]
        message_name = payload.get("message_name")
        sub_kind = SubscriptionKind.RECEIVE if payload.get("sub_kind") == "receive" else SubscriptionKind.CATCH
        if self._messages is not None and message_name:
            await self._messages.register(
                process_instance_id=pid, element_id=element_id, message_name=message_name,
                exception_id=instance.exception_id, correlation_id=instance.correlation_id,
                kind=sub_kind, interrupt_id=interrupt_id,
            )
        await self._instances.set_status(
            pid, InstanceStatus.WAITING_MESSAGE,
            expected=[InstanceStatus.RUNNING, InstanceStatus.CREATED],
        )
        logger.info("instance %s waiting_message: element=%s message=%s", pid, element_id, message_name)
        if self._messages is not None and message_name:
            buffered = await self._messages.pop_buffered(
                message_name, exception_id=instance.exception_id, correlation_id=instance.correlation_id)
            if buffered is not None:
                await self.deliver_message(
                    message_name, exception_id=instance.exception_id,
                    correlation_id=instance.correlation_id, payload=buffered.payload)

    async def _park_event_gateway(self, instance: ProcessInstance, payload: Dict[str, Any],
                                  *, interrupt_id: Optional[str]) -> None:
        """Register ALL arms of an event-based gateway (a timer for each timer catch, a subscription
        for each message catch) then park WAITING_MESSAGE. The first arm to fire wins."""
        pid = instance.process_instance_id
        gw = payload["element_id"]
        bundle = self.cached_bundle(instance.pack_key, instance.pack_version)
        model = bundle.bpmn_model if bundle else None
        arms = model.event_based_gateways.get(gw, []) if model else []
        for arm in arms:
            if model and arm in model.timer_catch_events and self._timers is not None:
                td = model.timer_catch_events[arm]
                await self._timers.register(
                    process_instance_id=pid, element_id=arm, kind=TimerKind.INTERMEDIATE,
                    fire_at=self._timers.fire_at(td), interrupt_id=interrupt_id, gateway_id=gw,
                    pack_key=instance.pack_key, pack_version=instance.pack_version,
                )
            elif model and arm in model.message_catch_events and self._messages is not None:
                await self._messages.register(
                    process_instance_id=pid, element_id=arm,
                    message_name=self._arm_message_name(bundle, arm) or "",
                    exception_id=instance.exception_id, correlation_id=instance.correlation_id,
                    kind=SubscriptionKind.EVENT_GATEWAY, interrupt_id=interrupt_id, gateway_id=gw,
                )
        await self._instances.set_status(
            pid, InstanceStatus.WAITING_MESSAGE,
            expected=[InstanceStatus.RUNNING, InstanceStatus.CREATED],
        )
        logger.info("instance %s waiting_message (event gateway %s, arms=%s)", pid, gw, arms)
        # ordering race: a message arm may already have a buffered message.
        for arm in arms:
            if model and arm in model.message_catch_events and self._messages is not None:
                mn = self._arm_message_name(bundle, arm)
                buffered = mn and await self._messages.pop_buffered(
                    mn, exception_id=instance.exception_id, correlation_id=instance.correlation_id)
                if buffered is not None:
                    await self.deliver_message(mn, exception_id=instance.exception_id,
                                               correlation_id=instance.correlation_id, payload=buffered.payload)
                    return

    async def _validate_message_payload(self, instance: ProcessInstance, element_id: str,
                                        payload: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Typed message: validate the payload against the binding's pinned output artifact schema and
        return the committed artifact map. Empty specs → untyped signal (``{}`` committed). Never
        commit malformed — a validation error is returned so delivery fails with a clear message."""
        specs = await self.output_specs(instance.pack_key, instance.pack_version, element_id)
        if not specs:
            return {}, None
        committed: Dict[str, Any] = {}
        for spec in specs:
            data = payload.get(spec.name) if (len(specs) > 1 and isinstance(payload, dict)) else payload
            errors = sorted(Draft202012Validator(spec.json_schema).iter_errors(data), key=lambda e: e.path)
            if errors:
                e = errors[0]
                loc = "/".join(str(p) for p in e.path)
                return None, f"{spec.schema_ref} invalid at '{loc or '<root>'}': {e.message}"
            committed[spec.name] = data
        return committed, None

    async def deliver_message(self, message_name: str, *, exception_id: Optional[str] = None,
                              correlation_id: Optional[str] = None, payload: Optional[dict] = None) -> Dict[str, Any]:
        """Correlate an inbound business message to a parked instance and resume it exactly once.

        Returns a status dict the HTTP intake maps to 202/404/409/422. Unmatched → the message is
        buffered (ordering race) and reported ``no_matching_subscription``; the first-wins guarded
        transition makes a duplicate delivery a safe ``already_consumed`` no-op."""
        if self._messages is None:
            return {"status": "no_matching_subscription"}
        sub = await self._messages.find_match(
            message_name, exception_id=exception_id, correlation_id=correlation_id)
        if sub is None:
            # A recently-consumed subscription for this message/anchor → a duplicate delivery (409),
            # distinct from an unknown message which is buffered for the ordering race (404).
            from app.models.message import SubscriptionStatus
            consumed = await self._messages.find_match(
                message_name, exception_id=exception_id, correlation_id=correlation_id,
                status=SubscriptionStatus.CONSUMED)
            if consumed is not None:
                return {"status": "already_consumed"}
            await self._messages.buffer_message(
                message_name=message_name, exception_id=exception_id,
                correlation_id=correlation_id, payload=payload)
            return {"status": "no_matching_subscription"}
        instance = await self._instances.get(sub.process_instance_id)
        if instance is None:
            return {"status": "no_matching_subscription"}
        # Typed payload (catch/receive): validate + commit BEFORE resuming; never commit malformed.
        committed: Dict[str, Any] = {}
        if sub.kind != SubscriptionKind.EVENT_GATEWAY:
            committed, verr = await self._validate_message_payload(instance, sub.element_id, payload)
            if verr is not None:
                return {"status": "invalid_payload", "detail": verr}
        # First-wins: whoever flips the parked instance to RUNNING delivers; a duplicate is a no-op.
        won = await self._instances.set_status(
            sub.process_instance_id, InstanceStatus.RUNNING, expected=[InstanceStatus.WAITING_MESSAGE])
        if won is None:
            return {"status": "already_consumed"}
        await self._messages.mark_consumed(sub.subscription_id)
        graph = await self.get_graph(instance.pack_key, instance.pack_version)
        if sub.kind == SubscriptionKind.EVENT_GATEWAY:
            await self._cancel_gateway_losers(instance, keep_element_id=sub.element_id)
            resume_val: Dict[str, Any] = {"arm": sub.element_id, "actor": "external",
                                          "actor_kind": "message", "payload": payload}
        else:
            resume_val = {"committed": committed} if committed else {"payload": payload}
        cmd = (Command(resume={sub.interrupt_id: resume_val}) if sub.interrupt_id
               else Command(resume=resume_val))
        await self._run_segment(instance, graph, cmd)
        await self._publish(MessageReceivedEvent(
            event_id=uuid.uuid4().hex, occurred_at=datetime.now(timezone.utc),
            process_instance_id=instance.process_instance_id, exception_id=instance.exception_id,
            element_id=sub.element_id, message_name=message_name,
            trace=Trace(correlation_id=instance.correlation_id),
        ))
        return {"status": "delivered", "process_instance_id": instance.process_instance_id}

    async def _cancel_gateway_losers(self, instance: ProcessInstance, *, keep_element_id: str) -> None:
        pid = instance.process_instance_id
        if self._messages is not None:
            await self._messages.cancel_others_for_instance(pid, keep_element_id=keep_element_id)
        if self._timers is not None:
            await self._timers.cancel_gateway_arms(pid, keep_element_id=keep_element_id)

    # ------------------------------------------------------------------ #
    # HITL task materialization
    # ------------------------------------------------------------------ #
    async def _materialize_task(self, instance: ProcessInstance, payload: Dict[str, Any],
                                state: Dict[str, Any], *, interrupt_id: Optional[str] = None) -> None:
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
        # ADR-027 Phase 2.2: if this HITL gate has an interrupting SLA timer boundary, compute its
        # fire_at NOW (so due_at actually *fires*, not just displays) and register a durable timer.
        element_id = payload["element_id"]
        boundary = (bundle.bpmn_model.boundary_timers.get(element_id) if bundle else None)
        boundary_fire_at = None
        due_at_iso = None
        if boundary is not None and self._timers is not None:
            try:
                boundary_fire_at = self._timers.fire_at(boundary.timer)
                due_at_iso = boundary_fire_at.isoformat()
            except Exception as exc:  # noqa: BLE001 - a malformed timer must not block the gate
                logger.warning("skipping SLA timer for %s: %s", element_id, exc)
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
            "interrupt_id": interrupt_id,
            "due_at": due_at_iso,
        }
        task = HitlTask.model_validate(task_doc)
        await self._hitl.insert(task)
        await self._instances.set_status(
            pid, InstanceStatus.WAITING_HITL,
            expected=[InstanceStatus.RUNNING, InstanceStatus.CREATED],
        )
        if boundary_fire_at is not None:
            await self._timers.register(
                process_instance_id=pid, element_id=element_id, kind=TimerKind.BOUNDARY,
                fire_at=boundary_fire_at, interrupt_id=interrupt_id, task_id=task_id,
                pack_key=instance.pack_key, pack_version=instance.pack_version,
            )
        logger.info("instance %s waiting_hitl: task %s element=%s mode=%s excluded=%s sla=%s",
                    pid, task_id, element_id, mode, excluded, due_at_iso)
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
