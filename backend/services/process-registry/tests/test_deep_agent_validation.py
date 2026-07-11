# tests/test_deep_agent_validation.py
"""ADR-021 — registry validation rules for the deep_agent kind (accept + each rejection).

Builds the wire-repair manifest but rebinds Task_AssessRepairability to a deep_agent
capability, registered alongside the seed. Reuses the seed BPMN/schemas (the agentic pilot
keeps the same IO).
"""
import json
from pathlib import Path

import pytest

from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from tests.conftest import SEED, load_bpmn, load_sample

_CAP = "cap.payment.assess_beneficiary_agentic"
# The pilot pack seed ships with the agent-runtime service (non-destructive: the standard
# seed is untouched). Onboard it through the registry front door end-to-end.
AGENTIC_SEED = Path(__file__).resolve().parents[2] / "agent-runtime" / "seed" / "wire-repair-agentic"


def _agentic_descriptor(*, side_effect="read_only", tools=None) -> CapabilityDescriptor:
    return CapabilityDescriptor.model_validate({
        "descriptor_version": "1.0", "capability_id": _CAP, "version": "1.0.0",
        "title": "Assess (agentic)", "kind": "deep_agent", "side_effect": side_effect,
        "idempotent": True,
        "inputs": [{"name": "dossier", "schema": "art.payment.investigation_dossier@^1.0.0"}],
        "outputs": [{"name": "beneficiary", "schema": "art.payment.repair_verdict@^1.0.0"}],
        "runtime": {"kind": "deep_agent", "prompt_key": "p", "model_config_key": "dev.llm.nemoclaw.nim",
                    "tools": tools if tools is not None else ["name_match", "screen_party"],
                    "structured_output": True},
        "constraints": {"timeout_seconds": 180, "max_retries": 1, "min_hitl_mode": "review_after"},
        "status": "active",
    })


def _manifest_binding_agentic(**over) -> dict:
    d = json.loads((SEED / "manifest.json").read_text())
    for b in d["bindings"]:
        if b["element_id"] == "Task_AssessRepairability":
            b["executor"]["capability"] = f"{_CAP}@^1.0.0"
            b.update(over.get("binding", {}))
    # keep requires_capabilities resolvable: add the agentic ref
    d["requires_capabilities"].append({"ref": f"{_CAP}@^1.0.0"})
    d.update({k: v for k, v in over.items() if k != "binding"})
    return d


async def _validate(validator, d):
    return await validator.validate(ProcessPackManifest.model_validate(d), load_bpmn(),
                                    sample_envelopes=[load_sample()])


def _errs(report):
    return set(report.error_codes())


@pytest.fixture
async def registered_with_agentic(registered, cap_repo):
    await cap_repo.insert(_agentic_descriptor())
    return cap_repo


# --------------------------------------------------------------------------- #
async def test_valid_agentic_pack_passes_with_nemoclaw_marker(registered_with_agentic, validator):
    report = await _validate(validator, _manifest_binding_agentic())
    assert report.ok, report.error_codes()
    # the pack is flagged as nemoclaw-mode-required (warning, non-blocking)
    assert any(f.code == "deep_agent_pack_requires_nemoclaw_mode" for f in report.findings)


async def test_deep_agent_without_hitl_gate_rejected(registered_with_agentic, validator):
    d = _manifest_binding_agentic(binding={"hitl": {"mode": "none"}})
    report = await _validate(validator, d)
    assert "deep_agent_requires_hitl" in _errs(report)


async def test_deep_agent_unresolved_tool_rejected(registered, cap_repo, validator):
    await cap_repo.insert(_agentic_descriptor(tools=["name_match", "totally_unknown_tool"]))
    report = await _validate(validator, _manifest_binding_agentic())
    assert "deep_agent_tool_unresolved" in _errs(report)


async def test_side_effectful_deep_agent_without_justification_rejected(registered, cap_repo, validator):
    await cap_repo.insert(_agentic_descriptor(side_effect="side_effectful"))
    # side_effectful also trips the generic approve_actions floor; assert the deep_agent code fires.
    report = await _validate(validator, _manifest_binding_agentic())
    assert "deep_agent_side_effect_not_justified" in _errs(report)


async def test_side_effectful_deep_agent_with_justification_clears_that_rule(registered, cap_repo, validator):
    await cap_repo.insert(_agentic_descriptor(side_effect="side_effectful"))
    d = _manifest_binding_agentic(
        deep_agent_justifications={_CAP: "audited: proposes only, human-gated at approve_actions"},
        binding={"hitl": {"mode": "approve_actions", "role": "role.payments.ops_approver"}},
    )
    report = await _validate(validator, d)
    assert "deep_agent_side_effect_not_justified" not in _errs(report)


@pytest.mark.skipif(not AGENTIC_SEED.exists(), reason="agentic pilot seed not present")
async def test_pilot_pack_onboards_clean_end_to_end(cap_repo, schema_repo, pack_repo, bpmn_repo):
    """The pilot pack, onboarded through the real pipeline (schema→cap→manifest→bpmn→validate
    →activate), validates clean and reaches ACTIVE — the same bar every prior pack cleared."""
    from app.seeding.onboard_seed import onboard

    result = await onboard(AGENTIC_SEED, cap_repo, schema_repo, pack_repo, bpmn_repo)
    assert result["validation"]["ok"], result["validation"]["errors"]
    assert "ACTIVE" in result["pack"]
    pack = await pack_repo.get("wire-repair-agentic", "1.0.0")
    assert pack.status.value == "active"
