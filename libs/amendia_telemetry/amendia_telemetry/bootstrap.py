# amendia_telemetry/bootstrap.py
"""One OTel bootstrap for every Amendia service — none hand-rolls the SDK (ADR-058 §4).

``configure_telemetry(service_name, app=…)`` installs a ``TracerProvider`` (+ a logs-provider
skeleton for Phase B) with Amendia resource attributes and an **OTLP/HTTP** exporter to the
Collector. It is **fail-soft by construction**:

  * **Endpoint absent ⇒ telemetry disabled.** No exporter is attached (spans/logs are dropped
    silently); the SDK still runs so instrumented code never branches. Set ``OTEL_DEBUG_CONSOLE``
    to print spans locally instead. So tests / local runs never hard-depend on the Collector.
  * **Collector down ⇒ no request impact.** The batch processor exports on a background thread;
    export failures are swallowed by the SDK, never surfaced to the request path.

The OTLP endpoint comes from the argument or the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` /
``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` env vars (so one compose env var wires every service).
Idempotent: safe to call more than once per process (tests build the app repeatedly).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from .conventions import RESOURCE_SERVICE_NAMESPACE

logger = logging.getLogger(__name__)

# Per-process guard — the tracer provider is global; re-configuring it warns and is pointless.
_state: Dict[str, Any] = {"configured": False}


def _traces_url(endpoint: str) -> str:
    """Normalize an OTLP/HTTP base (``http://host:4318``) to the traces signal URL.

    A base endpoint needs ``/v1/traces`` appended; a full signal endpoint is used as-is.
    """
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


def _logs_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/logs") else f"{endpoint}/v1/logs"


def _resolve_endpoint(endpoint: Optional[str]) -> Optional[str]:
    return (
        endpoint
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def configure_telemetry(
    service_name: str,
    *,
    app: Any = None,
    endpoint: Optional[str] = None,
    resource_attrs: Optional[Dict[str, Any]] = None,
) -> None:
    """Install the OTel providers for a service and (optionally) auto-instrument its FastAPI app.

    Call once at startup (e.g. inside ``create_app``). ``app`` — a FastAPI instance — gets HTTP
    handler auto-instrumentation. ``endpoint`` overrides the env; ``resource_attrs`` adds extra
    resource attributes. No-op-safe when the endpoint is unset (disabled) and when called twice.
    """
    if _state["configured"]:
        _instrument_app(app)
        return

    resolved = _resolve_endpoint(endpoint)
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": RESOURCE_SERVICE_NAMESPACE,
            **(resource_attrs or {}),
        }
    )

    provider = TracerProvider(resource=resource)
    if resolved:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=_traces_url(resolved))))
            logger.info("telemetry: %s → OTLP traces %s", service_name, _traces_url(resolved))
        except Exception as exc:  # noqa: BLE001 - never let telemetry setup break startup
            logger.warning("telemetry: OTLP span exporter unavailable (%s) — traces disabled", exc)
    elif os.environ.get("OTEL_DEBUG_CONSOLE"):
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        logger.info("telemetry: %s — no OTLP endpoint set, traces disabled", service_name)
    trace.set_tracer_provider(provider)

    # Logs provider skeleton — the audit system-of-record is Phase B (RabbitMQ → glea-service),
    # so Phase A only stands up the provider + a live OTLP logs pipeline for later use.
    _configure_logs(resource, resolved)

    _state["configured"] = True
    _instrument_app(app)


def _configure_logs(resource: Resource, endpoint: Optional[str]) -> None:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        lp = LoggerProvider(resource=resource)
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

            lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=_logs_url(endpoint))))
        set_logger_provider(lp)
    except Exception as exc:  # noqa: BLE001 - logs are a Phase-B skeleton; never break startup
        logger.debug("telemetry: logs provider skeleton not installed (%s)", exc)


def _instrument_app(app: Any) -> None:
    if app is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Idempotent per app; instrument_app tolerates being handed an already-instrumented app.
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        logger.debug("telemetry: FastAPI auto-instrumentation skipped (%s)", exc)


def get_tracer(name: str = "amendia"):
    """Convenience accessor for the global tracer (post-``configure_telemetry``)."""
    return trace.get_tracer(name)
