# tests/test_bpmn.py
from app.validation.bpmn import compute_sha256, parse_and_validate
from app.validation.report import ValidationReport
from tests.conftest import load_bpmn

NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'


def _report():
    return ValidationReport(pack_key="p", pack_version="1.0.0")


def _run(xml, process_id="P", sha=None):
    rep = _report()
    model = parse_and_validate(xml, expected_process_id=process_id,
                               expected_sha256=sha or compute_sha256(xml), report=rep)
    return model, rep


def _codes(rep):
    return {f.code for f in rep.findings if f.severity.value == "error"}


VALID = f"""<bpmn:definitions {NS}>
  <bpmn:process id="P">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:serviceTask id="t"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
    <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
    <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
  </bpmn:process>
</bpmn:definitions>"""


def test_minimal_valid_passes():
    model, rep = _run(VALID)
    assert model is not None
    assert not rep.has_errors
    assert model.tasks == {"t": "serviceTask"}


def test_seed_bpmn_passes_stage1():
    xml = load_bpmn()
    _, rep = _run(xml, process_id="Process_WireRepairStandard")
    assert not rep.has_errors


def test_sha_mismatch():
    _, rep = _run(VALID, sha="0" * 64)
    assert "bpmn_sha_mismatch" in _codes(rep)


def test_process_not_found_returns_none():
    model, rep = _run(VALID, process_id="Nope")
    assert model is None
    assert "bpmn_process_not_found" in _codes(rep)


def _warnings(rep):
    return {f.code for f in rep.findings if f.severity.value == "warning"}


def _infos(rep):
    return {f.code for f in rep.findings if f.severity.value == "info"}


def test_documented_element_is_warning_not_error():
    # ADR-027: a boundary event (recognized BPMN, not executable) is a WARNING, not a rejection.
    xml = f"""<bpmn:definitions {NS}>
      <bpmn:process id="P">
        <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:boundaryEvent id="b" attachedToRef="t"/>
        <bpmn:laneSet id="ls"/>
        <bpmn:serviceTask id="t"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
      </bpmn:process>
    </bpmn:definitions>"""
    model, rep = _run(xml)
    assert model is not None
    assert rep.ok  # documented elements never flip ok
    assert "bpmn_unsupported_element" not in _codes(rep)
    assert "bpmn_documented_element" in _warnings(rep)


def test_unknown_element_is_info():
    xml = f"""<bpmn:definitions {NS}>
      <bpmn:process id="P">
        <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:vendorThing id="v"/>
        <bpmn:serviceTask id="t"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
      </bpmn:process>
    </bpmn:definitions>"""
    _, rep = _run(xml)
    assert rep.ok
    assert "bpmn_unknown_element" in _infos(rep)


def test_unreachable_node():
    xml = f"""<bpmn:definitions {NS}>
      <bpmn:process id="P">
        <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:serviceTask id="t"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>
        <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
        <bpmn:serviceTask id="orphan"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
      </bpmn:process>
    </bpmn:definitions>"""
    _, rep = _run(xml)
    assert "bpmn_unreachable_node" in _codes(rep)


def test_conditionless_exclusive_flow():
    xml = f"""<bpmn:definitions {NS}>
      <bpmn:process id="P">
        <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
        <bpmn:exclusiveGateway id="g"><bpmn:incoming>f1</bpmn:incoming>
          <bpmn:outgoing>fa</bpmn:outgoing><bpmn:outgoing>fb</bpmn:outgoing></bpmn:exclusiveGateway>
        <bpmn:endEvent id="ea"><bpmn:incoming>fa</bpmn:incoming></bpmn:endEvent>
        <bpmn:endEvent id="eb"><bpmn:incoming>fb</bpmn:incoming></bpmn:endEvent>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="g"/>
        <bpmn:sequenceFlow id="fa" sourceRef="g" targetRef="ea"/>
        <bpmn:sequenceFlow id="fb" sourceRef="g" targetRef="eb"/>
      </bpmn:process>
    </bpmn:definitions>"""
    _, rep = _run(xml)
    assert "bpmn_conditionless_exclusive_flow" in _codes(rep)
