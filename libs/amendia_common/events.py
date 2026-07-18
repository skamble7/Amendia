# libs/astra_common/events.py
from __future__ import annotations
from enum import Enum

# Canonical exchange for all astra services
EXCHANGE = "amendia.events"

class Service(str, Enum):
    STUBEXCEPTION = "stub_exception"
    INGESTOR = "ingestor"
    AGENT_RUNTIME = "agent_runtime"

class Version(str, Enum):
    V1 = "v1"

# Canonical event names (the `<event>` segment of a routing key).
# Additive constants shared across services so producers and consumers agree
# on the wire vocabulary without hand-typing strings.
EXCEPTION_RAISED = "exception_raised"
EXCEPTION_DISPATCHED = "exception_dispatched"
DISPATCH_ACCEPTED = "dispatch_accepted"
DISPATCH_REJECTED = "dispatch_rejected"
HITL_TASK_CREATED = "hitl_task_created"
HITL_TASK_DECIDED = "hitl_task_decided"
# ADR-027 Phase 2.2 timers: a HITL gate breached its SLA and was escalated via its boundary timer;
# an intermediate-catch timer elapsed and the parked instance auto-proceeded.
HITL_TASK_EXPIRED = "hitl_task_expired"
TIMER_FIRED = "timer_fired"
# ADR-031 Phase 2.4: a correlated inbound business message was delivered to a parked instance.
MESSAGE_RECEIVED = "message_received"
PROCESS_COMPLETED = "process_completed"
PROCESS_FAILED = "process_failed"
# In-sandbox capability execution over the broker (ADR-020): the host publishes a job on the
# request key and the capability-worker publishes the correlated result (or replies directly).
CAPABILITY_EXEC_REQUEST = "capability_exec_request"
CAPABILITY_EXEC_RESULT = "capability_exec_result"

def rk(service: Service | str, event: str, version: str = Version.V1.value) -> str:
    """
    Build the canonical versioned routing key:
        <service>.<event>.<version>

    Examples:
        rk(Service.ARTIFACT, "created") -> "artifact.created.v1"
    """
    svc = service.value if isinstance(service, Service) else str(service)
    return f"{svc}.{event}.{version}"