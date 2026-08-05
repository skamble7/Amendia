# worker/main.py
"""capability-worker entrypoint. Run as a plain process (dev/CI) or inside an OpenShell
sandbox (prod, via `nemoclaw onboard`):

    python -m worker.main
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from amendia_telemetry import configure_telemetry

from app.config import settings
from app.logging_conf import configure_logging
from worker.consumer import CapabilityWorkerConsumer

logger = logging.getLogger(__name__)


async def _run() -> None:
    consumer = CapabilityWorkerConsumer(settings.RABBITMQ_URL, settings.CAPABILITY_EXEC_REQUEST_QUEUE)
    loop = asyncio.get_event_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass
    task = asyncio.create_task(consumer.run())
    logger.info(
        "capability-worker ready (simulation=%s, mcp_registry=%s, inference=%s)",
        settings.SIMULATION_MODE, settings.MCP_REGISTRY_PATH, settings.WORKER_INFERENCE_BASE_URL,
    )
    await stop.wait()
    await consumer.stop()
    task.cancel()


def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    # ADR-058: stand up the worker's OWN TracerProvider so its ``sandbox.capability`` execution spans
    # export to the Collector, parented (via ``emit_linked_span``) to the node span whose W3C
    # traceparent the host threaded down in the job spec — so a real cross-process capability run
    # unifies into the one instance trace instead of vanishing. Endpoint: the standard
    # ``OTEL_EXPORTER_OTLP_ENDPOINT`` (dev compose → otel-collector) else ``settings.OTLP_ENDPOINT``
    # (the in-sandbox host endpoint in prod nemoclaw). Unreachable ⇒ fail-soft (spans dropped on a
    # background thread); no endpoint at all ⇒ telemetry disabled — the worker never crashes on either.
    endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
                or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                or settings.OTLP_ENDPOINT)
    configure_telemetry("agent-runtime-worker", endpoint=endpoint)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
