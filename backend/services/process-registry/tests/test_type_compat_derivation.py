# tests/test_type_compat_derivation.py
"""ADR-052 follow-up — at copilot DERIVATION (reconcile._capability_input_sources) a trigger-sourced field
whose JSON type can't satisfy the tool field is surfaced as a warning (CopilotOpenQuestion), so the operator
repoints it; the mapping is still emitted (the commit validator is the hard gate)."""
from types import SimpleNamespace

from app.services.copilot.proposal import InputMapProposal
from app.services.copilot.reconcile import Reconciler

_PARTY_TOOL = {"properties": {"party": {"type": "object", "properties": {
    "name": {"type": "string"}, "account": {"type": "string"}}}}}   # tool: party.account = STRING

_TRIGGER_OBJ_ACCT = {"type": "object", "properties": {"payment": {"type": "object", "properties": {
    "creditor": {"type": "object", "properties": {
        "account": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}}}   # creditor.account = OBJECT

_TRIGGER_STR_ACCT = {"type": "object", "properties": {"payment": {"type": "object", "properties": {
    "creditor": {"type": "object", "properties": {"account": {"type": "string"}}}}}}}   # creditor.account = STRING


def _recon(tool_input_schema, trigger_schema) -> Reconciler:
    r = Reconciler.__new__(Reconciler)           # bypass heavy __init__; set only what the method touches
    r.tools_by_name = {"screen_party": SimpleNamespace(input_schema=tool_input_schema)}
    r.user_trigger_schema = trigger_schema
    r.questions = []
    r.decisions = []
    r.flow_graph = None                          # → _is_optional_source honors m.optional (here None)
    return r


def _proposal(path):
    return SimpleNamespace(input_map=[InputMapProposal(field="party", **{"from": "trigger"}, path=path)])


def test_derivation_warns_on_object_into_string():
    r = _recon(_PARTY_TOOL, _TRIGGER_OBJ_ACCT)
    out = r._capability_input_sources("Screen", "screen_party", _proposal("payment.creditor"))
    # mapping still emitted (operator sees it in the wizard)…
    assert out["screen_party_input"]["fields"]["party"] == {"from": "trigger", "path": "payment.creditor"}
    # …plus a warning naming the element + field
    warns = [q for q in r.questions if q.topic == "input_map" and q.element_id == "Screen" and "party" in q.question]
    assert warns, r.questions


def test_derivation_no_warn_on_compatible_source():
    r = _recon(_PARTY_TOOL, _TRIGGER_STR_ACCT)
    r._capability_input_sources("Screen", "screen_party", _proposal("payment.creditor"))
    assert not r.questions
