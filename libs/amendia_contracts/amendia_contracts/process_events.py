# amendia_contracts/process_events.py
"""Thin process-lifecycle events published by the agent-runtime.

Emitted when a process instance reaches a terminal state. Consumers (platform /
notification services) fetch instance detail from the runtime's read API.
"""
from __future__ import annotations

from typing import ClassVar, Literal, Optional

from amendia_common.events import PROCESS_COMPLETED, PROCESS_FAILED, Service
from amendia_contracts.common import EventBase
from amendia_contracts.dispatch import Trace


class ProcessCompletedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = PROCESS_COMPLETED

    schema_version: Literal["pin.platform.process_completed/1.0"] = "pin.platform.process_completed/1.0"
    process_instance_id: str
    exception_id: str
    pack_key: str
    pack_version: str
    outcome: str
    trace: Trace


class ProcessFailedEvent(EventBase):
    _service: ClassVar[Service] = Service.AGENT_RUNTIME
    _event_name: ClassVar[str] = PROCESS_FAILED

    schema_version: Literal["pin.platform.process_failed/1.0"] = "pin.platform.process_failed/1.0"
    process_instance_id: str
    exception_id: str
    pack_key: str
    pack_version: str
    reason: str
    detail: Optional[str] = None
    trace: Trace
