# app/engine/executor/base.py
"""Executor context + error types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class CapabilityError(Exception):
    """A capability failed to execute (bad descriptor, import error, runtime raise)."""


@dataclass
class ExecutionContext:
    """Per-invocation context handed to the executor + capability.

    ``mode`` is ``propose`` (approve_actions pre-gate) or ``execute``.
    ``approved_action_ids`` narrows execution to a subset after a partial approval.
    """

    envelope: Dict[str, Any]
    mode: str = "execute"
    approved_action_ids: Optional[List[str]] = None
    simulation: bool = True
    extras: Dict[str, Any] = field(default_factory=dict)
