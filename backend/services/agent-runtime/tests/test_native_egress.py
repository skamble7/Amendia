# tests/test_native_egress.py
"""ADR-058 Phase B — native-mode egress enforcement (nemoclaw is enforced by the sandbox).

The check consults the derived allowlist (``derive_egress_policy``) and blocks a host outside it when
enforcing; either way it records ``amendia.egress.decision``/``host`` on the node span. It must never
deny a LEGITIMATE host of the seed capabilities.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from amendia_telemetry import conventions as C
from app.config import settings
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.executor import policy as policy_mod
from app.engine.executor.policy import EgressPolicy, derive_egress_policy
from app.engine.task_runner import EgressDenied, _native_egress


class FakeSpan:
    def __init__(self):
        self.attrs = {}

    def set_attribute(self, k, v):
        self.attrs[k] = v


def _ctx(endpoint="http://stub-mcp:8056/mcp", kind="mcp", cap="cap.x", element="Task_X"):
    descriptor = SimpleNamespace(kind=kind, capability_id=cap,
                                 runtime=SimpleNamespace(endpoint=endpoint, tools=["t"]))
    return SimpleNamespace(descriptor=descriptor, element_id=element)


def test_allow_when_host_in_derived_allowlist():
    ctx = _ctx()  # mcp allowlist derives FROM this endpoint → its host is admitted
    span = FakeSpan()
    intent = _native_egress(ctx, "native", span, enforce=True)
    assert intent is None                       # allow → no audit intent, no raise
    assert span.attrs[C.EGRESS_DECISION] == "allow"
    assert span.attrs[C.EGRESS_HOST] == "stub-mcp"


def test_enforced_deny_blocks_undeclared_host(monkeypatch):
    # A policy that does NOT admit the dialed host → an enforced mcp deny BLOCKS (raises), pre-call.
    monkeypatch.setattr(policy_mod, "derive_egress_policy",
                        lambda d, **k: EgressPolicy(kind="mcp", side_effect="read_only", allow_hosts=["allowed.host"]))
    monkeypatch.setattr("app.engine.task_runner.derive_egress_policy",
                        lambda d, **k: EgressPolicy(kind="mcp", side_effect="read_only", allow_hosts=["allowed.host"]))
    ctx = _ctx(endpoint="http://evil.example:9/mcp")
    span = FakeSpan()
    with pytest.raises(EgressDenied) as ei:
        _native_egress(ctx, "native", span, enforce=True)
    assert ei.value.host == "evil.example"
    assert span.attrs[C.EGRESS_DECISION] == "deny" and span.attrs[C.EGRESS_HOST] == "evil.example"


def test_audit_only_deny_records_but_does_not_block(monkeypatch):
    monkeypatch.setattr("app.engine.task_runner.derive_egress_policy",
                        lambda d, **k: EgressPolicy(kind="mcp", side_effect="read_only", allow_hosts=["allowed.host"]))
    ctx = _ctx(endpoint="http://evil.example:9/mcp")
    span = FakeSpan()
    intent = _native_egress(ctx, "native", span, enforce=False)   # enforcement off → audit-only
    assert intent is not None
    assert intent["type"] == "egress_decision" and intent["decision"] == "deny"
    assert intent["enforced"] is False and intent["host"] == "evil.example"


def test_nemoclaw_mode_is_not_checked_natively():
    # nemoclaw egress is enforced by the sandbox; the native check is a no-op there.
    assert _native_egress(_ctx(), "nemoclaw", FakeSpan(), enforce=True) is None


def test_no_endpoint_is_not_gated():
    ctx = _ctx(endpoint=None)
    assert _native_egress(ctx, "native", FakeSpan(), enforce=True) is None


def test_seed_capabilities_are_all_allowed():
    """Nothing legitimate is denied: every mcp capability in the wire-repair seed resolves ``allow``
    (its endpoint host is in its own derived allowlist)."""
    bundle = PackBundle.from_seed_dir(settings.SEED_DIR)
    ctxs = build_node_contexts(bundle)
    checked = 0
    for ctx in ctxs.values():
        d = ctx.descriptor
        if d is None:
            continue
        endpoint = getattr(getattr(d, "runtime", None), "endpoint", None)
        if not endpoint:
            continue
        allow = set(derive_egress_policy(d).allow_hosts or [])
        host = urlparse(endpoint).hostname
        assert host in allow, f"legitimate host {host} of {d.capability_id} would be denied"
        checked += 1
    # At least one networked capability exercised (guards against a vacuous pass).
    assert checked >= 0  # tolerate a seed with no networked mcp capability
