# worker/main.py
"""capability-worker entrypoint. Run as a plain process (dev/CI) or inside an OpenShell
sandbox (prod, via `nemoclaw onboard`):

    python -m worker.main
"""
from __future__ import annotations

import asyncio
import logging
import signal

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
    asyncio.run(_run())


if __name__ == "__main__":
    main()
