# wire_transfer_exception_mcp
"""A standalone, deterministic ("dumb") MCP server exposing the ten tools that back the
``wire-repair-agentic`` process pack's capabilities. Amendia-MCP-compliant: every tool
declares both an ``inputSchema`` and an ``outputSchema``; the three action tools return an
acknowledgement object. See ``schemas.py`` (the contract) and ``handlers.py`` (dumb handlers).
"""
from .handlers import TOOLS, TOOLS_BY_NAME, check_compliance

__all__ = ["TOOLS", "TOOLS_BY_NAME", "check_compliance", "__version__"]
__version__ = "0.1.0"
