# backend/tests/smoke/conftest.py
"""Session fixtures + the stack-readiness preflight. The suite is a *smoke*, not a deployer: if the stack
isn't reachable it **skips with a clear message** rather than erroring."""
from __future__ import annotations

import httpx
import pytest

from .client import Tokens, stack_down_reason
from .config import load_config


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "smoke: full-stack corpus smoke test (needs a running, onboarded compose stack)")


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def http():
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        yield client


@pytest.fixture(scope="session")
def tokens(cfg, http):
    return Tokens(cfg, http)


@pytest.fixture(scope="session", autouse=True)
def stack_ready(cfg):
    """Preflight: skip the WHOLE suite (cleanly) when the core stack isn't reachable."""
    reason = stack_down_reason(cfg)
    if reason:
        pytest.skip(reason)
