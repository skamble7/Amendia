# libs/astra_common/events.py
from __future__ import annotations
from enum import Enum

# Canonical exchange for all astra services
EXCHANGE = "amendia.events"

class Service(str, Enum):
    STUBEXCEPTION = "stub_exception"

class Version(str, Enum):
    V1 = "v1"

# Canonical event names (the `<event>` segment of a routing key).
# Additive constants shared across services so producers and consumers agree
# on the wire vocabulary without hand-typing strings.
EXCEPTION_RAISED = "exception_raised"

def rk(org: str, service: Service | str, event: str, version: str = Version.V1.value) -> str:
    """
    Build the canonical versioned routing key:
        <org>.<service>.<event>.<version>

    Examples:
        rk("acme", Service.ARTIFACT, "created") -> "acme.artifact.created.v1"
    """
    svc = service.value if isinstance(service, Service) else str(service)
    return f"{org}.{svc}.{event}.{version}"