"""OpenShell client abstraction (ADR-017, transport pivoted in ADR-020).

All sandbox I/O lives behind ``OpenShellClient``. Implementations:
  * ``FakeOpenShellClient`` — deterministic, in-process; the CI/dev default (no broker).
  * ``BrokerOpenShellClient`` — the real ``nemoclaw`` path: broker request/reply to the
    in-sandbox ``capability-worker`` (ADR-020), since OpenShell has no inbound execute API.
  * ``HttpOpenShellClient`` — **retired** (ADR-019/020): OpenShell exposes no host→gateway
    execute RPC. Kept guarded (raises) with a pointer; never selected.
"""
from app.engine.executor.openshell.broker import (
    BrokerOpenShellClient,
    BrokerTransport,
    InMemoryBrokerTransport,
    RabbitBrokerTransport,
    spec_to_job,
)
from app.engine.executor.openshell.client import (
    CapabilityRunSpec,
    FakeOpenShellClient,
    HttpOpenShellClient,
    OpenShellClient,
    SandboxResult,
)

__all__ = [
    "OpenShellClient",
    "CapabilityRunSpec",
    "SandboxResult",
    "FakeOpenShellClient",
    "HttpOpenShellClient",
    "BrokerOpenShellClient",
    "BrokerTransport",
    "InMemoryBrokerTransport",
    "RabbitBrokerTransport",
    "spec_to_job",
]
