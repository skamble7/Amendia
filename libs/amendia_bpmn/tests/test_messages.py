"""ADR-031 / Phase 2.4 — message catch, receive task, event-based gateway: parse, capture, profile."""
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


def _catch_xml() -> str:
    defs = '<bpmn:message id="Msg_Reply" name="rfi_reply"/>'
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Ask"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:intermediateCatchEvent id="AwaitReply"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing>'
        '<bpmn:messageEventDefinition messageRef="Msg_Reply"/></bpmn:intermediateCatchEvent>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Ask"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Ask" targetRef="AwaitReply"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="AwaitReply" targetRef="E"/>'
    )
    return _doc(inner, defs)


def _receive_xml() -> str:
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:receiveTask id="Recv"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:receiveTask>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Recv"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Recv" targetRef="E"/>'
    )
    return _doc(inner)


def _event_gateway_xml(bad_arm=False) -> str:
    """start → Screen → eventGateway → { message catch: result | timer catch: timeout } → ends."""
    defs = '<bpmn:message id="Msg_Result" name="screening_result"/>'
    arm2 = (
        '<bpmn:intermediateCatchEvent id="Timeout"><bpmn:incoming>ga</bpmn:incoming><bpmn:outgoing>ft</bpmn:outgoing>'
        '<bpmn:timerEventDefinition><bpmn:timeDuration>PT1H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
    ) if not bad_arm else (
        '<bpmn:serviceTask id="Timeout"><bpmn:incoming>ga</bpmn:incoming><bpmn:outgoing>ft</bpmn:outgoing></bpmn:serviceTask>'
    )
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Screen"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:eventBasedGateway id="Gw"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>gm</bpmn:outgoing><bpmn:outgoing>ga</bpmn:outgoing></bpmn:eventBasedGateway>'
        '<bpmn:intermediateCatchEvent id="Result"><bpmn:incoming>gm</bpmn:incoming><bpmn:outgoing>fm</bpmn:outgoing>'
        '<bpmn:messageEventDefinition messageRef="Msg_Result"/></bpmn:intermediateCatchEvent>'
        + arm2 +
        '<bpmn:endEvent id="EndOk"><bpmn:incoming>fm</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:endEvent id="EndTo"><bpmn:incoming>ft</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Screen"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Screen" targetRef="Gw"/>'
        '<bpmn:sequenceFlow id="gm" sourceRef="Gw" targetRef="Result"/>'
        '<bpmn:sequenceFlow id="ga" sourceRef="Gw" targetRef="Timeout"/>'
        '<bpmn:sequenceFlow id="fm" sourceRef="Result" targetRef="EndOk"/>'
        '<bpmn:sequenceFlow id="ft" sourceRef="Timeout" targetRef="EndTo"/>'
    )
    return _doc(inner, defs)


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


def test_messages_ranks_above_error_boundary():
    assert profile_rank("messages") == profile_rank("common_executable") == 1 > profile_rank("common_subset")


def test_message_catch_captured_and_bindable():
    m, _ = parse(_catch_xml(), "P", profile="messages")
    assert m.message_catch_events == {"AwaitReply": "rfi_reply"}
    assert m.bindable_elements()["AwaitReply"] == "messageCatch"
    assert next(e for e in m.elements if e.id == "AwaitReply").tier == "executable"
    m2, _ = parse(_catch_xml(), "P", profile="common_subset")
    assert next(e for e in m2.elements if e.id == "AwaitReply").tier == "documented"
    assert required_profile(m) == "common_executable"


def test_receive_task_captured_and_bindable():
    m, _ = parse(_receive_xml(), "P", profile="messages")
    assert "Recv" in m.receive_tasks
    assert m.bindable_elements()["Recv"] == "receiveTask"
    assert required_profile(m) == "common_executable"


def test_event_gateway_arms_and_wellformed():
    m, _ = parse(_event_gateway_xml(), "P", profile="messages")
    assert m.event_based_gateways["Gw"] == ["Result", "Timeout"]
    assert compilability_findings(m, profile="messages") == []
    assert required_profile(m) == "common_executable"


def test_event_gateway_arm_must_be_catch():
    m, _ = parse(_event_gateway_xml(bad_arm=True), "P", profile="messages")
    assert "bpmn_event_gateway_arm_not_catch" in _codes(m, "messages")


def test_message_constructs_refused_under_lower_profile():
    m, _ = parse(_catch_xml(), "P", profile="error_boundary")
    assert "bpmn_message_unsupported" in _codes(m, "common_subset")
    assert "bpmn_message_unsupported" in _codes(m, "common_subset")
