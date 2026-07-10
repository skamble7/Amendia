# tests/test_execution_mode.py
"""ADR-017 Part E — executor selection, fail-closed, and degrade-to-native.

Hermetic: no live gateway. ``build_executor`` is exercised with the deterministic fake
(auto-selected when ``OPENSHELL_URL`` is unset) and with injected unreachable stubs.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.engine.executor import (
    InProcessExecutor,
    NemoClawUnavailable,
    SandboxedExecutor,
    build_executor,
)
from app.engine.executor.openshell import FakeOpenShellClient


def _settings(**over):
    base = dict(
        EXECUTION_MODE="native",
        OPENSHELL_URL=None,
        NEMOCLAW_REQUIRED=False,
        SANDBOX_POOL_SIZE=4,
        SIMULATION_MODE=True,
        LLM_CONFIG_REF="dev.llm.bedrock.explicit-creds",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Unreachable:
    """An OpenShellClient whose reachability probe fails (no gateway)."""

    async def ping(self) -> bool:
        return False

    async def run_capability(self, spec):  # pragma: no cover - never reached
        raise AssertionError("unreachable client should not execute")


def test_native_mode_returns_in_process_executor():
    ex = build_executor(_settings(EXECUTION_MODE="native"))
    assert isinstance(ex, InProcessExecutor)


def test_nemoclaw_mode_with_fake_returns_sandboxed_executor():
    # No OPENSHELL_URL → deterministic fake → reachable → SandboxedExecutor.
    ex = build_executor(_settings(EXECUTION_MODE="nemoclaw"))
    assert isinstance(ex, SandboxedExecutor)


def test_nemoclaw_required_and_unreachable_fails_closed():
    with pytest.raises(NemoClawUnavailable):
        build_executor(
            _settings(EXECUTION_MODE="nemoclaw", NEMOCLAW_REQUIRED=True),
            client=_Unreachable(),
        )


def test_nemoclaw_not_required_and_unreachable_degrades_to_native():
    ex = build_executor(
        _settings(EXECUTION_MODE="nemoclaw", NEMOCLAW_REQUIRED=False),
        client=_Unreachable(),
    )
    assert isinstance(ex, InProcessExecutor)


def test_injected_fake_client_is_used():
    fake = FakeOpenShellClient(simulation=True)
    ex = build_executor(_settings(EXECUTION_MODE="nemoclaw"), client=fake)
    assert isinstance(ex, SandboxedExecutor)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_executor(_settings(EXECUTION_MODE="bogus"))
