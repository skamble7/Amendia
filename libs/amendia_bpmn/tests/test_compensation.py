"""ADR-043 / Item G — compensation (explicit compensate-throw + reverse-order undo). The parser pairs a
compensable primary to an ``isForCompensation`` undo handler via a compensate boundary + association, and
records compensate-throw events; the off-flow handler is excluded from reachability/arity. Deferred
variants (transaction/cancel, targeted ``activityRef``, multi-instance) are refused.
"""
from amendia_bpmn import compilability_findings, parse, required_profile

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">')
_FTR = "</bpmn:definitions>"


def _doc(inner: str, defs: str = "") -> str:
    return f'{_HDR}{defs}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


def _handler(hid="Reverse", primary="Release", mi="") -> str:
    return (f'<bpmn:serviceTask id="{hid}" isForCompensation="true">{mi}</bpmn:serviceTask>'
            f'<bpmn:boundaryEvent id="{hid}Bnd" attachedToRef="{primary}"><bpmn:compensateEventDefinition/></bpmn:boundaryEvent>'
            f'<bpmn:association sourceRef="{hid}Bnd" targetRef="{hid}"/>')


def _throw(tid="CompThrow", *, is_end=True, activity_ref="", incoming="f_fail", outgoing="") -> str:
    ref = f' activityRef="{activity_ref}"' if activity_ref else ""
    if is_end:
        return f'<bpmn:endEvent id="{tid}"><bpmn:incoming>{incoming}</bpmn:incoming><bpmn:compensateEventDefinition{ref}/></bpmn:endEvent>'
    return (f'<bpmn:intermediateThrowEvent id="{tid}"><bpmn:incoming>{incoming}</bpmn:incoming>'
            f'<bpmn:outgoing>{outgoing}</bpmn:outgoing><bpmn:compensateEventDefinition{ref}/></bpmn:intermediateThrowEvent>')


# start → Release → Gw → (ok → End_Done) / (fail → throw). Release is the compensable primary.
def _proc(*, handler_xml=None, throw_xml=None, throw_after=None, primary_mi="") -> str:
    handler_xml = _handler() if handler_xml is None else handler_xml
    throw_xml = _throw() if throw_xml is None else throw_xml
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        f'<bpmn:serviceTask id="Release"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>{primary_mi}</bpmn:serviceTask>'
        '<bpmn:exclusiveGateway id="Gw" default="f_ok"><bpmn:incoming>f2</bpmn:incoming>'
        '<bpmn:outgoing>f_ok</bpmn:outgoing><bpmn:outgoing>f_fail</bpmn:outgoing></bpmn:exclusiveGateway>'
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f_ok</bpmn:incoming></bpmn:endEvent>'
        + throw_xml + (throw_after or "") +
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Release"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Release" targetRef="Gw"/>'
        '<bpmn:sequenceFlow id="f_ok" sourceRef="Gw" targetRef="End_Done"/>'
        '<bpmn:sequenceFlow id="f_fail" sourceRef="Gw" targetRef="CompThrow">'
        '<bpmn:conditionExpression>artifacts.rel.ok == false</bpmn:conditionExpression></bpmn:sequenceFlow>'
        + handler_xml)
    return _doc(inner)


def _codes(model, profile="common_executable"):
    return {f.code for f in compilability_findings(model, profile=profile)}


def _errs(findings):
    return {f.code for f in findings if f.severity == "error"}


# --- parse the triad -----------------------------------------------------------------------------

def test_compensation_triad_parsed():
    m, findings = parse(_proc(), "P", profile="common_executable")
    assert _errs(findings) == set(), _errs(findings)
    assert m.compensation_handlers["Reverse"].primary_id == "Release"
    assert m.compensation_handlers["Reverse"].boundary_id == "ReverseBnd"
    assert m.compensations == {"Release": "Reverse"}
    thr = m.compensate_throws["CompThrow"]
    assert thr.is_end is True and thr.scope == "P" and thr.activity_ref is None
    # the handler is a bound task but OFF the flow → not falsely unreachable / no arity error
    assert "Reverse" in m.tasks
    assert "bpmn_unreachable_node" not in {f.code for f in findings}
    assert "bpmn_no_path_to_end" not in {f.code for f in findings}
    assert _codes(m) == set()
    assert required_profile(m) == "common_executable"


def test_intermediate_throw_parsed():
    throw = _throw(is_end=False, outgoing="f3")
    after = ('<bpmn:endEvent id="End_Comp"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
             '<bpmn:sequenceFlow id="f3" sourceRef="CompThrow" targetRef="End_Comp"/>')
    m, findings = parse(_proc(throw_xml=throw, throw_after=after), "P", profile="common_executable")
    assert _errs(findings) == set(), _errs(findings)
    assert m.compensate_throws["CompThrow"].is_end is False
    assert _codes(m) == set()


# --- refusals ------------------------------------------------------------------------------------

def test_targeted_compensation_refused():
    m, _ = parse(_proc(throw_xml=_throw(activity_ref="Release")), "P", profile="common_executable")
    assert "bpmn_compensation_targeted_unsupported" in _codes(m)


def test_transaction_cancel_refused():
    # a cancel end event present alongside compensation → deferred transaction auto-compensation
    cancel = ('<bpmn:endEvent id="Cancel"><bpmn:incoming>fx</bpmn:incoming><bpmn:cancelEventDefinition/></bpmn:endEvent>'
              '<bpmn:sequenceFlow id="fx" sourceRef="Gw" targetRef="Cancel"/>')
    m, _ = parse(_proc(throw_after=cancel), "P", profile="common_executable")
    assert "Cancel" in m.cancel_end_events
    assert "bpmn_compensation_transaction_unsupported" in _codes(m)


def test_multi_instance_compensation_refused():
    mi = ('<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>3</bpmn:loopCardinality>'
          '</bpmn:multiInstanceLoopCharacteristics>')
    m, _ = parse(_proc(primary_mi=mi), "P", profile="common_executable")
    assert "bpmn_compensation_multi_instance_unsupported" in _codes(m)


def test_compensate_throw_no_handlers_warns():
    # a compensate throw but NO compensation boundary/handler → no compensable activities → warning
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Release"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="CompThrow"><bpmn:incoming>f2</bpmn:incoming><bpmn:compensateEventDefinition/></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Release"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Release" targetRef="CompThrow"/>')
    m, findings = parse(_doc(inner), "P", profile="common_executable")
    warns = {f.code for f in compilability_findings(m, profile="common_executable") if f.severity == "warning"}
    assert "bpmn_compensate_throw_no_handlers" in warns
    assert _errs(compilability_findings(m, profile="common_executable")) == set()  # a no-op, not an error


def test_compensation_boundary_without_association_refused():
    # a compensate boundary but no <association> to a handler → unwired
    bad_handler = ('<bpmn:serviceTask id="Reverse" isForCompensation="true"></bpmn:serviceTask>'
                   '<bpmn:boundaryEvent id="ReverseBnd" attachedToRef="Release"><bpmn:compensateEventDefinition/></bpmn:boundaryEvent>')
    m, findings = parse(_proc(handler_xml=bad_handler), "P", profile="common_executable")
    assert "bpmn_compensation_boundary_unwired" in {f.code for f in findings}
    assert "Reverse" not in m.compensation_handlers
