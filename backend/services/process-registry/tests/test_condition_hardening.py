# tests/test_condition_hardening.py
"""Condition hardening: Tier-1 normalization (Camunda ${…} unwrap + inference win) and Tier-2 guided,
blocking validation, exercised end-to-end against the seed wire-repair pack (gateway ``Gateway_Repairable``,
condition ``beneficiary.repair_verdict = "repairable"`` → output ``art.payment.assess_beneficiary_output``
whose required string fields are ``repair_verdict`` (enum) + ``rationale``)."""
from __future__ import annotations

import json

from amendia_bpmn import extract_semantics, select_process_id
from amendia_contracts.process_pack import ProcessPackManifest
from app.services.inference import build_semantic_summary, infer_draft
from tests.conftest import SEED, load_bpmn, load_sample

GOLDEN = 'beneficiary.repair_verdict = "repairable"'


def _manifest() -> dict:
    return json.loads((SEED / "manifest.json").read_text())


def _bpmn_with(cond: str) -> str:
    xml = load_bpmn()
    assert GOLDEN in xml
    return xml.replace(GOLDEN, cond)


def _gateway_conditions(xml: str):
    sem = extract_semantics(xml, select_process_id(xml))
    return build_semantic_summary(sem)["gateway_conditions"], sem


async def _validate(validator, xml: str):
    return await validator.validate(ProcessPackManifest.model_validate(_manifest()), xml,
                                    sample_envelopes=[load_sample()])


def _cond_issues(report):
    return [f for f in report.findings if f.code == "gateway_condition_grammar"]


# --- Tier-1: golden untouched ------------------------------------------------------------------------
async def test_golden_condition_untouched_and_passes(registered, validator):
    gcs, _ = _gateway_conditions(load_bpmn())
    for gc in gcs:
        assert gc["changes"] == [] and gc["canonical"] == gc["raw"]     # no auto-conversion
    report = await _validate(validator, load_bpmn())
    assert _cond_issues(report) == [] and report.condition_issues == []


# --- Tier-1: Camunda unwrap → inference win + Tier-2 missing_field -----------------------------------
async def test_camunda_unwrap_normalizes_infers_and_flags_missing_field(registered, validator):
    xml = _bpmn_with('${beneficiary == "repairable"}')
    gcs, sem = _gateway_conditions(xml)
    hit = next(g for g in gcs if g["canonical"] == 'beneficiary == "repairable"')
    assert hit["changes"] == ["unwrapped ${…} expression"]
    assert hit["variable"] == "beneficiary"                             # infers now (was a silent blank)

    # the inference draft resolves a gateway variable for that gateway (Source artifact resolvable downstream)
    draft = infer_draft(sem, "payment")
    assert any(gv.gateway_id == "Gateway_Repairable" for gv in draft.gateway_variables)

    # Tier-2: field-less LHS → blocking missing_field with a schema-drawn suggestion
    report = await _validate(validator, xml)
    issues = _cond_issues(report)
    mf = next(f for f in issues if f.reason == "missing_field")
    assert report.has_errors                                           # cannot go active
    assert mf.suggestion["condition"] == 'beneficiary.repair_verdict = "repairable"'
    assert "repair_verdict" in mf.suggestion["candidate_fields"]
    assert report.condition_issues                                     # surfaced as a first-class list


# --- Tier-2: the production case (unquoted RHS) blocks -----------------------------------------------
async def test_unquoted_boolean_rhs_is_blocking_and_guided(registered, validator):
    report = await _validate(validator, _bpmn_with("limit_breached = true"))
    issues = _cond_issues(report)
    reasons = {f.reason for f in issues}
    assert "unquoted_rhs" in reasons and "missing_field" in reasons    # both, per the production failure
    assert report.has_errors                                           # pack cannot go active
    uq = next(f for f in issues if f.reason == "unquoted_rhs")
    assert 'must be a double-quoted string' in uq.message
    # suggestion is drawn from the bound output's required string fields
    assert uq.suggestion["candidate_fields"]


# --- Tier-1: unsupported operator + ambiguous-left-untouched ----------------------------------------
async def test_unsupported_operator_blocks(registered, validator):
    report = await _validate(validator, _bpmn_with('beneficiary.repair_verdict > "repairable"'))
    issues = _cond_issues(report)
    assert any(f.reason == "unsupported_operator" for f in issues) and report.has_errors


async def test_single_quote_condition_is_normalized_then_passes(registered, validator):
    # 'repairable' → "repairable": lossless, so the condition still parses and produces NO Tier-2 issue.
    xml = _bpmn_with("beneficiary.repair_verdict = 'repairable'")
    gcs, _ = _gateway_conditions(xml)
    hit = next(g for g in gcs if g["canonical"] == GOLDEN)
    assert hit["changes"] == ["converted single-quoted literal to double-quoted"]
    report = await _validate(validator, xml)
    assert _cond_issues(report) == []
