from pydantic import BaseModel, Field
from typing import Any, Optional

class EventEnvelope(BaseModel):
    specversion: str = "1.0"
    id: str
    type: str                           # e.g., "discovery.completed"
    source: str                         # e.g., "raina.discovery-service"
    subject: Optional[str] = None       # e.g., "workspace:<id>"
    time: str                           # ISO8601
    datacontenttype: str = "application/json"
    data: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
