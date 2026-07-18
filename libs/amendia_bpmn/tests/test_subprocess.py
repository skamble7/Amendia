"""ADR-032 / Phase 2.6 — embedded sub-process: scoped start/end, flatten, profile, deferred refusals."""
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


def _doc(inner: str, defs: str = "") -> str:
    return f'{_HDR}{defs}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


def _sub(sub_id, body, *, incoming, outgoing) -> str:
    return (f'<bpmn:subProcess id="{sub_id}"><bpmn:incoming>{incoming}</bpmn:incoming>'
            f'<bpmn:outgoing>{outgoing}</bpmn:outgoing>{body}</bpmn:subProcess>')


def _embedded(*, sub_body=None, sub_extra="") -> str:
    """start → Enrich → Sub[ SubStart → Inner → SubEnd ] → End."""
    body = sub_body if sub_body is not None else (
        '<bpmn:startEvent id="SubStart"><bpmn:outgoing>sf1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Inner"><bpmn:incoming>sf1</bpmn:incoming><bpmn:outgoing>sf2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="SubEnd"><bpmn:incoming>sf2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="sf1" sourceRef="SubStart" targetRef="Inner"/>'
        '<bpmn:sequenceFlow id="sf2" sourceRef="Inner" targetRef="SubEnd"/>')
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Enrich"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        + _sub("Sub", body + sub_extra, incoming="f2", outgoing="f3") +
        '<bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Enrich"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Enrich" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Sub" targetRef="E"/>')
    return _doc(inner)


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


def test_subprocess_ranks_above_messages():
    assert profile_rank("subprocess") == profile_rank("common_executable") == 1 > profile_rank("common_subset")


def test_embedded_subprocess_scoped_start_end():
    model, findings = parse(_embedded(), "P", profile="subprocess")
    codes = {f.code for f in findings}
    # the NESTED start does not inflate the top-level single-start rule
    assert "bpmn_start_event_count" not in codes
    assert model.start_events == ["S"] and model.end_events == ["E"]
    sub = model.subprocesses["Sub"]
    assert sub.start_id == "SubStart" and sub.end_ids == ["SubEnd"]
    assert sub.incoming_flow == "f2" and sub.outgoing_flow == "f3"
    # nested task is flattened into the executable collections + bindable; container is NOT bindable
    assert "Inner" in model.tasks
    assert model.bindable_elements()["Inner"] == "serviceTask"
    assert "Sub" not in model.bindable_elements()
    assert required_profile(model) == "common_executable"
    assert compilability_findings(model, profile="subprocess") == []


def test_subprocess_container_executable_tier_under_profile():
    model, _ = parse(_embedded(), "P", profile="subprocess")
    assert next(e for e in model.elements if e.id == "Sub").tier == "executable"
    model2, _ = parse(_embedded(), "P", profile="common_subset")
    assert next(e for e in model2.elements if e.id == "Sub").tier == "documented"


def test_subprocess_missing_start_or_end_rejected():
    no_start = (
        '<bpmn:serviceTask id="Inner"><bpmn:incoming>sf1</bpmn:incoming><bpmn:outgoing>sf2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="SubEnd"><bpmn:incoming>sf2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="sf2" sourceRef="Inner" targetRef="SubEnd"/>')
    m, findings = parse(_embedded(sub_body=no_start), "P", profile="subprocess")
    assert "bpmn_subprocess_start_count" in {f.code for f in findings}

    no_end = (
        '<bpmn:startEvent id="SubStart"><bpmn:outgoing>sf1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Inner"><bpmn:incoming>sf1</bpmn:incoming></bpmn:serviceTask>'
        '<bpmn:sequenceFlow id="sf1" sourceRef="SubStart" targetRef="Inner"/>')
    m2, findings2 = parse(_embedded(sub_body=no_end), "P", profile="subprocess")
    assert "bpmn_subprocess_no_end" in {f.code for f in findings2}


def test_refused_under_lower_profiles():
    m, _ = parse(_embedded(), "P", profile="messages")
    assert "bpmn_subprocess_unsupported" in _codes(m, "common_subset")
    assert "bpmn_subprocess_unsupported" in _codes(m, "common_subset")


def test_call_activity_deferred():
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:callActivity id="Call" calledElement="OtherProcess"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:callActivity>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Call"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Call" targetRef="E"/>')
    m, _ = parse(_doc(inner), "P", profile="subprocess")
    assert "Call" in m.call_activities
    assert "bpmn_call_activity_unsupported" in _codes(m, "subprocess")


def test_subprocess_boundary_deferred():
    boundary = ('<bpmn:boundaryEvent id="Bnd" attachedToRef="Sub"><bpmn:timerEventDefinition>'
                '<bpmn:timeDuration>PT1H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>'
                '<bpmn:sequenceFlow id="fb" sourceRef="Bnd" targetRef="E"/>')
    m, _ = parse(_embedded(sub_extra="").replace("</bpmn:process>", boundary + "</bpmn:process>"), "P", profile="subprocess")
    assert m.subprocess_boundaries == ["Bnd"]
    assert "bpmn_subprocess_boundary_unsupported" in _codes(m, "subprocess")


def test_substrate_constructs_flatten_inside_a_subprocess():
    # A timer catch, a message catch, and an error boundary INSIDE a sub-process flatten into the
    # executable collections (scope-tagged) — so the compiler wires them exactly as at top level.
    defs = ('<bpmn:message id="M" name="reply"/>'
            '<bpmn:error id="Er" errorCode="REJECTED"/>')
    sub_body = (
        '<bpmn:startEvent id="SubStart"><bpmn:outgoing>a1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:intermediateCatchEvent id="Wait"><bpmn:incoming>a1</bpmn:incoming><bpmn:outgoing>a2</bpmn:outgoing>'
        '<bpmn:timerEventDefinition><bpmn:timeDuration>PT1H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
        '<bpmn:intermediateCatchEvent id="Recv"><bpmn:incoming>a2</bpmn:incoming><bpmn:outgoing>a3</bpmn:outgoing>'
        '<bpmn:messageEventDefinition messageRef="M"/></bpmn:intermediateCatchEvent>'
        '<bpmn:serviceTask id="NestedApply"><bpmn:incoming>a3</bpmn:incoming><bpmn:outgoing>a4</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="SubEnd"><bpmn:incoming>a4</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:userTask id="Rework"><bpmn:incoming>eb</bpmn:incoming><bpmn:outgoing>a5</bpmn:outgoing></bpmn:userTask>'
        '<bpmn:endEvent id="SubEnd2"><bpmn:incoming>a5</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:boundaryEvent id="Bnd" attachedToRef="NestedApply"><bpmn:errorEventDefinition errorRef="Er"/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="a1" sourceRef="SubStart" targetRef="Wait"/>'
        '<bpmn:sequenceFlow id="a2" sourceRef="Wait" targetRef="Recv"/>'
        '<bpmn:sequenceFlow id="a3" sourceRef="Recv" targetRef="NestedApply"/>'
        '<bpmn:sequenceFlow id="a4" sourceRef="NestedApply" targetRef="SubEnd"/>'
        '<bpmn:sequenceFlow id="eb" sourceRef="Bnd" targetRef="Rework"/>'
        '<bpmn:sequenceFlow id="a5" sourceRef="Rework" targetRef="SubEnd2"/>')
    m, _ = parse(_embedded(sub_body=sub_body), "P", profile="subprocess")
    assert "Wait" in m.timer_catch_events
    assert "Recv" in m.message_catch_events
    assert "NestedApply" in m.error_boundaries
    # all scope-tagged to the sub-process
    assert m.element_scope["Wait"] == "Sub" and m.element_scope["NestedApply"] == "Sub"
    assert compilability_findings(m, profile="subprocess") == []


def test_nested_two_levels():
    deep = (
        '<bpmn:startEvent id="SubStart"><bpmn:outgoing>sf1</bpmn:outgoing></bpmn:startEvent>'
        + _sub("Sub2",
               '<bpmn:startEvent id="S2"><bpmn:outgoing>g1</bpmn:outgoing></bpmn:startEvent>'
               '<bpmn:serviceTask id="Deep"><bpmn:incoming>g1</bpmn:incoming><bpmn:outgoing>g2</bpmn:outgoing></bpmn:serviceTask>'
               '<bpmn:endEvent id="E2"><bpmn:incoming>g2</bpmn:incoming></bpmn:endEvent>'
               '<bpmn:sequenceFlow id="g1" sourceRef="S2" targetRef="Deep"/>'
               '<bpmn:sequenceFlow id="g2" sourceRef="Deep" targetRef="E2"/>',
               incoming="sf1", outgoing="sf2")
        + '<bpmn:endEvent id="SubEnd"><bpmn:incoming>sf2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="sf1" sourceRef="SubStart" targetRef="Sub2"/>'
        '<bpmn:sequenceFlow id="sf2" sourceRef="Sub2" targetRef="SubEnd"/>')
    m, findings = parse(_embedded(sub_body=deep), "P", profile="subprocess")
    assert set(m.subprocesses) == {"Sub", "Sub2"}
    assert m.subprocesses["Sub2"].parent_scope == "Sub"
    assert "Deep" in m.tasks
    assert compilability_findings(m, profile="subprocess") == [], [f.code for f in findings]
