"""ACH-exposure Assess-segment MCP stub — deterministic capability tools for the Amendia cohort worked example."""
from __future__ import annotations

__all__ = ["main"]


def main() -> None:  # thin re-export so `python -m ach_exposure_assess_mcp` works
    from .server import main as _main

    _main()
