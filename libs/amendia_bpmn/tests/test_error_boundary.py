"""ADR-030 / Phase 2.3 — error boundary events: parse, capture, coverage tier, profile gate."""
from amendia_bpmn import (
    EXECUTION_PROFILES,
    compilability_findings,
    parse,
    profile_rank,
    required_profile,
)

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">')
_FTR = "</bpmn:definitions>"


def _doc(process_inner: str, errors: str = "") -> str:
    return (f"{_HDR}{errors}"
            f'<bpmn:process id="P" isExecutable="true">{process_inner}</bpmn:process>{_FTR}')


def _apply_reject(*, code_ref="Err_Rejected", second=None, catch_all=False) -> str:
    """start → Apply (serviceTask) → End; Apply has error boundary(s) → rework/end targets."""
    errdefs = '<bpmn:error id="Err_Rejected" errorCode="PAYMENT_REJECTED"/>'
    boundaries = (
        f'<bpmn:boundaryEvent id="Bnd1" attachedToRef="Apply">'
        f'<bpmn:errorEventDefinition errorRef="{code_ref}"/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="be1" sourceRef="Bnd1" targetRef="Rework"/>'
    )
    if second is not None:
        errdefs += '<bpmn:error id="Err_Screen" errorCode="SCREENING_HIT"/>'
        boundaries += (
            f'<bpmn:boundaryEvent id="Bnd2" attachedToRef="Apply">'
            f'<bpmn:errorEventDefinition errorRef="{second}"/></bpmn:boundaryEvent>'
            '<bpmn:sequenceFlow id="be2" sourceRef="Bnd2" targetRef="Hold"/>'
            '<bpmn:userTask id="Hold"><bpmn:incoming>be2</bpmn:incoming><bpmn:outgoing>fh</bpmn:outgoing></bpmn:userTask>'
            '<bpmn:endEvent id="EndHold"><bpmn:incoming>fh</bpmn:incoming></bpmn:endEvent>'
            '<bpmn:sequenceFlow id="fh" sourceRef="Hold" targetRef="EndHold"/>'
        )
    if catch_all:
        boundaries += (
            '<bpmn:boundaryEvent id="BndAny" attachedToRef="Apply">'
            '<bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
            '<bpmn:sequenceFlow id="bea" sourceRef="BndAny" targetRef="Rework"/>'
        )
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Apply"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="EndOk"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:userTask id="Rework"><bpmn:incoming>be1</bpmn:incoming><bpmn:outgoing>fr</bpmn:outgoing></bpmn:userTask>'
        '<bpmn:endEvent id="EndRework"><bpmn:incoming>fr</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Apply"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Apply" targetRef="EndOk"/>'
        '<bpmn:sequenceFlow id="fr" sourceRef="Rework" targetRef="EndRework"/>'
        + boundaries
    )
    return _doc(inner, errors=errdefs)


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


def test_error_boundary_captured_with_code_and_target():
    m, _ = parse(_apply_reject(), "P", profile="error_boundary")
    ebs = m.error_boundaries["Apply"]
    assert len(ebs) == 1
    assert ebs[0].error_code == "PAYMENT_REJECTED" and ebs[0].target == "Rework"
    # the boundary's outgoing flow is not a normal edge
    assert all(f.source != "Bnd1" for f in m.flows)
    # executable under the profile; documented under a lower one
    assert next(e for e in m.elements if e.id == "Bnd1").tier == "executable"
    m2, _ = parse(_apply_reject(), "P", profile="common_subset")
    assert next(e for e in m2.elements if e.id == "Bnd1").tier == "documented"
    assert "Apply" in m2.error_boundaries  # captured regardless of profile


def test_catch_all_boundary_has_none_code():
    m, _ = parse(_apply_reject(code_ref="Err_Rejected", catch_all=True), "P", profile="error_boundary")
    codes = {eb.error_code for eb in m.error_boundaries["Apply"]}
    assert codes == {"PAYMENT_REJECTED", None}  # None = the catch-all


def test_required_profile_and_hierarchy():
    assert profile_rank("error_boundary") == profile_rank("common_executable") == 1 > profile_rank("common_subset")
    m, _ = parse(_apply_reject(), "P", profile="error_boundary")
    assert required_profile(m) == "common_executable"


def test_refused_under_lower_profiles():
    m, _ = parse(_apply_reject(), "P", profile="timers")
    assert "bpmn_error_boundary_unsupported" in _codes(m, "common_subset")
    assert "bpmn_error_boundary_unsupported" in _codes(m, "common_subset")


def test_wellformed_passes_under_profile():
    m, _ = parse(_apply_reject(second="Err_Screen", catch_all=True), "P", profile="error_boundary")
    assert compilability_findings(m, profile="error_boundary") == []


def test_ambiguous_duplicate_code_rejected():
    # two boundaries catching the same errorRef → ambiguous
    m, _ = parse(_apply_reject(second="Err_Rejected"), "P", profile="error_boundary")
    assert "bpmn_error_boundary_ambiguous" in _codes(m, "error_boundary")


def test_unwired_error_boundary_stays_documented():
    # an error boundary with no outgoing flow is documentation-only.
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Apply"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:boundaryEvent id="Bnd1" attachedToRef="Apply"><bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Apply"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Apply" targetRef="E"/>'
    )
    m, _ = parse(_doc(inner), "P", profile="error_boundary")
    assert m.error_boundaries == {}
    assert compilability_findings(m, profile="error_boundary") == []
