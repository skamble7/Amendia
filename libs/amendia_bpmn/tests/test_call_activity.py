"""ADR-039 / Backlog #1 — callActivity (cross-pack composition): parse, capture, profile gate, refusals."""
from amendia_bpmn import (
    DEFAULT_CALL_VERSION_RANGE,
    compilability_findings,
    parse,
    profile_rank,
    required_profile,
)

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:amendia="http://amendia.example/bpmn">')
_FTR = "</bpmn:definitions>"


def _doc(inner: str) -> str:
    return f'{_HDR}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


def _call(*, called='callee-pack', version='^2.0.0', mi=False, boundary=False) -> str:
    ce = f' calledElement="{called}"' if called else ""
    cv = f' amendia:calledVersion="{version}"' if version else ""
    mi_inner = ('<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2</bpmn:loopCardinality>'
                '</bpmn:multiInstanceLoopCharacteristics>') if mi else ""
    extra = ""
    if boundary:
        extra = ('<bpmn:boundaryEvent id="Bnd" attachedToRef="CA"><bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
                 '<bpmn:sequenceFlow id="fb" sourceRef="Bnd" targetRef="Rework"/>'
                 '<bpmn:userTask id="Rework"><bpmn:incoming>fb</bpmn:incoming><bpmn:outgoing>fr</bpmn:outgoing></bpmn:userTask>'
                 '<bpmn:endEvent id="ER"><bpmn:incoming>fr</bpmn:incoming></bpmn:endEvent>'
                 '<bpmn:sequenceFlow id="fr" sourceRef="Rework" targetRef="ER"/>')
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        f'<bpmn:callActivity id="CA"{ce}{cv}><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>{mi_inner}</bpmn:callActivity>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="CA"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="CA" targetRef="E"/>'
        + extra
    )
    return _doc(inner)


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


# --------------------------------------------------------------------------- #
def test_call_activity_captured():
    m, _ = parse(_call(), "P", profile="common_executable")
    ca = m.call_activities["CA"]
    assert ca.target_pack == "callee-pack"
    assert ca.version_range == "^2.0.0"
    assert ca.is_multi_instance is False


def test_default_version_range_when_absent():
    m, _ = parse(_call(version=None), "P", profile="common_executable")
    assert m.call_activities["CA"].version_range == DEFAULT_CALL_VERSION_RANGE


def test_call_activity_is_bindable_element():
    m, _ = parse(_call(), "P", profile="common_executable")
    assert m.bindable_elements().get("CA") == "callActivity"


def test_required_profile_common_executable():
    m, _ = parse(_call(), "P", profile="common_executable")
    assert required_profile(m) == "common_executable"
    assert profile_rank("common_executable") > profile_rank("common_subset")


def test_refused_under_common_subset():
    m, _ = parse(_call(), "P", profile="common_subset")
    assert "bpmn_call_activity_unsupported" in _codes(m, "common_subset")
    assert "CA" in m.call_activities  # captured regardless of profile


def test_wellformed_passes_under_common_executable():
    m, _ = parse(_call(), "P", profile="common_executable")
    assert compilability_findings(m, profile="common_executable") == []


def test_tier_flips_by_profile():
    m, _ = parse(_call(), "P", profile="common_executable")
    assert next(e for e in m.elements if e.id == "CA").tier == "executable"
    m2, _ = parse(_call(), "P", profile="common_subset")
    assert next(e for e in m2.elements if e.id == "CA").tier == "documented"


# --------------------------------------------------------------------------- #
# Structural refusals
# --------------------------------------------------------------------------- #
def test_no_target_refused():
    m, _ = parse(_call(called=None), "P", profile="common_executable")
    assert m.call_activities["CA"].target_pack is None
    assert "bpmn_call_activity_no_target" in _codes(m, "common_executable")


def test_multi_instance_host_refused():
    m, _ = parse(_call(mi=True), "P", profile="common_executable")
    assert m.call_activities["CA"].is_multi_instance is True
    assert "bpmn_call_activity_multi_instance_unsupported" in _codes(m, "common_executable")


def test_boundary_on_call_activity_refused():
    m, _ = parse(_call(boundary=True), "P", profile="common_executable")
    assert "bpmn_subprocess_boundary_unsupported" in _codes(m, "common_executable")
