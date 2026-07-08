"""Capability executor: kind-dispatch (skill / llm / mcp) with a simulation seam."""
from app.engine.executor.base import CapabilityError, ExecutionContext
from app.engine.executor.dispatch import Executor

__all__ = ["CapabilityError", "ExecutionContext", "Executor"]
