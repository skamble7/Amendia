# app/engine/executor/openshell/broker.py
"""Host side of the in-sandbox capability execution (ADR-020): broker request/reply.

The transport is **inverted** vs. the dead HTTP scaffold (ADR-019): the host never calls
into the sandbox. It publishes a job on ``agent_runtime.capability_exec_request.v1`` and
awaits the correlated reply the ``capability-worker`` (running *inside* the egress-only
sandbox) publishes back. This preserves the `OpenShellClient` seam — `run_capability(spec)
-> SandboxResult` is unchanged; only the implementation swaps to broker request/reply.

Two transports: ``InMemoryBrokerTransport`` (drives the worker runner in-process — the CI/unit
substrate, no RabbitMQ) and ``RabbitBrokerTransport`` (real aio-pika RPC, env-gated
integration). ``BrokerOpenShellClient`` is transport-agnostic: it builds the job, enforces the
timeout, retries only if idempotent, and maps the reply to ``SandboxResult``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

from amendia_common.events import CAPABILITY_EXEC_REQUEST, EXCHANGE, Service, rk

from app.engine.executor.base import CapabilityError
from app.engine.executor.memo import inputs_hash
from app.engine.executor.openshell.client import CapabilityRunSpec, SandboxResult

logger = logging.getLogger(__name__)

REQUEST_RK = rk(Service.AGENT_RUNTIME, CAPABILITY_EXEC_REQUEST)
_DEFAULT_TIMEOUT = 120.0


def _request_id(spec: CapabilityRunSpec) -> str:
    """Deterministic per (instance, element, inputs, attempt) → idempotent under redelivery;
    combines naturally with the ADR-019 host memo. Falls back to a content hash when the
    instance/element aren't set (e.g. ad-hoc calls)."""
    pid = spec.process_instance_id or "noinst"
    el = spec.element_id or spec.capability_id
    return f"{pid}:{el}:{inputs_hash(spec.inputs)}:{spec.memo_attempt}"


def spec_to_job(spec: CapabilityRunSpec) -> Dict[str, Any]:
    """Serialize a spec into a broker job. Secrets never cross: ``model_config_ref`` is a
    ref, and the descriptor carries refs only (ADR-017 trap 3)."""
    d = spec.descriptor
    descriptor_dump = d.model_dump(by_alias=True, mode="json") if hasattr(d, "model_dump") else d
    return {
        "capability_id": spec.capability_id,
        "kind": spec.kind,
        "inputs": spec.inputs,
        "envelope": spec.envelope,
        "output_schemas": spec.output_schemas,
        "mode": spec.mode,
        "approved_action_ids": spec.approved_action_ids,
        "model_config_ref": spec.model_config_ref,
        "element_id": spec.element_id,
        "process_instance_id": spec.process_instance_id,
        "memo_attempt": spec.memo_attempt,
        "simulation": spec.simulation,
        "egress_policy": spec.egress_policy,
        "descriptor": descriptor_dump,
    }


class BrokerTransport(Protocol):
    async def request(self, job: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
        ...

    async def ping(self) -> bool:
        ...


class InMemoryBrokerTransport:
    """Drives the worker runner in-process — no RabbitMQ. The CI/unit substrate. ``latency``
    and ``drop`` let tests exercise timeout/retry paths deterministically."""

    def __init__(self, handler: Callable[[Dict[str, Any]], Dict[str, Any]],
                 *, latency: float = 0.0, drop: bool = False, reachable: bool = True) -> None:
        self._handler = handler
        self._latency = latency
        self._drop = drop
        self._reachable = reachable
        self.calls = 0

    async def request(self, job, *, timeout):
        self.calls += 1
        if self._drop:
            await asyncio.sleep(timeout + 1)  # never replies → caller's wait_for times out
        if self._latency:
            await asyncio.sleep(self._latency)
        return self._handler(job)

    async def ping(self):
        return self._reachable


class RabbitBrokerTransport:
    """Real aio-pika request/reply (env-gated integration). Per-call connection because the
    sync↔async bridge (`_run_blocking`) runs each call on a fresh event loop (ADR-016)."""

    def __init__(self, url: str, *, request_rk: str = REQUEST_RK) -> None:
        self._url = url
        self._request_rk = request_rk

    async def request(self, job, *, timeout):
        import aio_pika

        conn = await aio_pika.connect_robust(self._url, timeout=15)
        try:
            ch = await conn.channel()
            exchange = await ch.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
            callback_q = await ch.declare_queue(exclusive=True, auto_delete=True)
            loop = asyncio.get_event_loop()
            fut: asyncio.Future = loop.create_future()
            corr = job["request_id"]

            async def on_reply(msg: "aio_pika.abc.AbstractIncomingMessage") -> None:
                async with msg.process(ignore_processed=True):
                    if msg.correlation_id == corr and not fut.done():
                        fut.set_result(json.loads(msg.body.decode("utf-8")))

            await callback_q.consume(on_reply)
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(job, default=str).encode("utf-8"),
                    content_type="application/json",
                    correlation_id=corr,
                    reply_to=callback_q.name,
                ),
                routing_key=self._request_rk,
            )
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            await conn.close()

    async def ping(self):
        import aio_pika

        try:
            conn = await aio_pika.connect_robust(self._url, timeout=10)
            await conn.close()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("BrokerTransport ping failed: %s", exc)
            return False


class BrokerOpenShellClient:
    """`OpenShellClient` over the broker. Selected in nemoclaw mode when the capability-worker
    is enabled (`AGENTRT_CAPABILITY_WORKER_ENABLED`); the fake stays the default otherwise."""

    def __init__(self, transport: BrokerTransport, *, default_timeout: float = _DEFAULT_TIMEOUT) -> None:
        self._transport = transport
        self._default_timeout = default_timeout

    async def ping(self) -> bool:
        return await self._transport.ping()

    async def run_capability(self, spec: CapabilityRunSpec) -> SandboxResult:
        job = {"request_id": _request_id(spec), "spec": spec_to_job(spec)}
        timeout = spec.timeout_seconds or self._default_timeout
        attempts = (spec.max_retries if spec.idempotent else 0) + 1
        last_err: Optional[str] = None

        for i in range(attempts):
            try:
                reply = await asyncio.wait_for(
                    self._transport.request(job, timeout=timeout), timeout=timeout
                )
            except asyncio.TimeoutError:
                last_err = f"capability-worker timed out after {timeout}s"
                logger.warning("%s (attempt %d/%d)", last_err, i + 1, attempts)
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = f"broker transport error: {exc}"
                continue

            if not reply.get("ok"):
                last_err = reply.get("error", "capability-worker error")
                if not spec.idempotent:
                    break  # deterministic failure — don't retry non-idempotent work
                continue

            r = reply.get("result", {})
            return SandboxResult(
                outputs=r.get("outputs", {}) or {},
                otlp_trace_id=r.get("otlp_trace_id", "otlp-unknown"),
                provider=r.get("provider"),
                model=r.get("model"),
                proposed_actions=r.get("proposed_actions"),
                log=r.get("log"),
            )

        raise CapabilityError(
            f"{spec.capability_id}: capability-worker failed after {attempts} attempt(s): {last_err}"
        )
