"""OpenShell client abstraction (ADR-017).

All sandbox I/O lives behind ``OpenShellClient`` so Phase 1 is testable now (with the
deterministic ``FakeOpenShellClient``) and the live NemoClaw gateway drops in later
(``HttpOpenShellClient``) without touching the executor or the pure graph nodes.
"""
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
]
