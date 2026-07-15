# tests/test_egress_policy.py
"""ADR-019 Part C — egress/tool policy derived from contract data, per capability kind.

No parallel hand-maintained list: the policy is a pure function of the descriptor. Uses the
real seed descriptors (mcp sanctions, side-effectful apply_repair, llm draft_repair, read-only
enrich).
"""
from __future__ import annotations

from app.config import settings
from app.engine.bundle import PackBundle
from app.engine.executor.policy import INFERENCE_PROXY_HOST, derive_egress_policy


def _descriptors():
    return PackBundle.from_seed_dir(settings.SEED_DIR).descriptors


def test_mcp_policy_from_endpoint_and_tools():
    d = _descriptors()["cap.payment.sanctions_screen"]  # kind mcp
    p = derive_egress_policy(d).to_dict()
    assert p["kind"] == "mcp"
    assert p["mcp"]["endpoint"]                     # self-descriptive endpoint (ADR-024)
    assert p["mcp"]["tools"]                        # non-empty whitelist from runtime.tools
    assert p["mcp"]["transport"]                    # from runtime.transport
    assert any("stub-mcp" in h for h in p["allow_hosts"])  # egress host parsed from the endpoint


def test_llm_policy_restricts_to_inference_proxy():
    d = _descriptors()["cap.payment.draft_repair"]  # kind llm
    p = derive_egress_policy(d).to_dict()
    assert p["kind"] == "llm"
    assert p["inference_proxy_host"] == INFERENCE_PROXY_HOST
    assert INFERENCE_PROXY_HOST in p["allow_hosts"]


def test_side_effect_skill_policy_marks_stub_endpoints():
    d = _descriptors()["cap.payment.apply_repair"]  # kind skill, side_effectful
    p = derive_egress_policy(d).to_dict()
    assert p["kind"] == "skill"
    assert p["side_effect"] == "side_effectful"
    # endpoints derived from config_schema (may be empty → stub-only in dev), and a note says so
    assert any("simulated" in n for n in p["notes"])


def test_read_only_skill_policy_minimal_egress():
    d = _descriptors()["cap.payment.enrich_investigation"]  # kind skill, read_only
    p = derive_egress_policy(d).to_dict()
    assert p["kind"] == "skill"
    assert p["side_effect"] == "read_only"
    assert p["mcp"] is None
    assert any("read-only" in n for n in p["notes"])
