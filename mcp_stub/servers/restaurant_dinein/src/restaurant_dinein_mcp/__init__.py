# restaurant_dinein_mcp
"""Deterministic (dumb) MCP server exposing the six restaurant dine-in capability tools for Amendia
onboarding + runtime integration — the domain-simple "hello world" twin of the
``wire_transfer_exception`` reference server (ADR-047 D2: zero domain code in the platform image;
the process runs as onboarded data + this external MCP server)."""
from __future__ import annotations

from .handlers import TOOLS, TOOLS_BY_NAME, check_compliance

__all__ = ["TOOLS", "TOOLS_BY_NAME", "check_compliance"]
