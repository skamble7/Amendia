"""ADR-033 / Phase 2.7 — task-kind coverage: send/script/manual/businessRule + the executor map."""
from amendia_bpmn import (
    EXECUTION_PROFILES,
    EXTENDED_TASK_KINDS,
    TASK_EXECUTOR_CATEGORY,
    compilability_findings,
    parse,
    profile_rank,
    required_profile,
)

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">')
_FTR = "</bpmn:definitions>"


def _proc(inner: str) -> str:
    return f'{_HDR}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


def _linear(task_xml: str, task_id: str) -> str:
    """start → <task on the live path> → end."""
    return _proc(
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        + task_xml +
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        f'<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="{task_id}"/>'
        f'<bpmn:sequenceFlow id="f2" sourceRef="{task_id}" targetRef="E"/>')


def _task(kind: str, tid: str, *, script=False) -> str:
    body = '<bpmn:script>x = 1</bpmn:script>' if script else ''
    return (f'<bpmn:{kind} id="{tid}"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
            f'{body}</bpmn:{kind}>')


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


def test_tasks_is_final_top_of_hierarchy():
    assert EXECUTION_PROFILES == ["common_subset", "common_executable"]
    assert profile_rank("tasks") == profile_rank("common_executable") == 1 > profile_rank("common_subset")


def test_executor_category_map_covers_the_task_set():
    assert TASK_EXECUTOR_CATEGORY["sendTask"] == "capability"
    assert TASK_EXECUTOR_CATEGORY["scriptTask"] == "capability"
    assert TASK_EXECUTOR_CATEGORY["businessRuleTask"] == "capability"
    assert TASK_EXECUTOR_CATEGORY["manualTask"] == "human"
    assert TASK_EXECUTOR_CATEGORY["serviceTask"] == "capability"
    assert TASK_EXECUTOR_CATEGORY["userTask"] == "human"
    assert TASK_EXECUTOR_CATEGORY["receiveTask"] == "message"


def test_each_new_kind_captured_and_bindable_and_promoted():
    for kind in ("sendTask", "scriptTask", "manualTask", "businessRuleTask"):
        m, _ = parse(_linear(_task(kind, "T"), "T"), "P", profile="tasks")
        assert m.tasks["T"] == kind
        assert m.bindable_elements()["T"] == kind          # joins the bijection
        assert next(e for e in m.elements if e.id == "T").tier == "executable"
        assert required_profile(m) == "common_executable"
        # documented (not executable) under a lower profile
        m2, _ = parse(_linear(_task(kind, "T"), "T"), "P", profile="common_subset")
        assert next(e for e in m2.elements if e.id == "T").tier == "documented"


def test_refused_under_lower_profile():
    m, _ = parse(_linear(_task("sendTask", "T"), "T"), "P", profile="subprocess")
    assert "bpmn_task_kind_unsupported" in _codes(m, "common_subset")
    assert "bpmn_task_kind_unsupported" in _codes(m, "common_subset")
    assert compilability_findings(m, profile="tasks") == []


def test_business_rule_task_decision_ref_captured():
    xml = _linear('<bpmn:businessRuleTask id="Rule" calledDecision="Dec_X">'
                  '<bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:businessRuleTask>', "Rule")
    m, _ = parse(xml, "P", profile="tasks")
    assert m.decision_refs["Rule"] == "Dec_X"       # advisory (no DMN eval)


def test_inline_script_always_refused():
    m, _ = parse(_linear(_task("scriptTask", "T", script=True), "T"), "P", profile="tasks")
    assert "T" in m.inline_scripts
    assert "bpmn_inline_script_unsupported" in _codes(m, "tasks")


def test_isolated_floating_task_stays_documented():
    # a fully-disconnected extended task is decoration, not an unreachable-node error.
    xml = _proc(
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:businessRuleTask id="Floating" calledDecision="D"/>'   # isolated decoration
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="E"/>')
    m, findings = parse(xml, "P", profile="tasks")
    assert "Floating" not in m.tasks                              # not an executable node
    assert "bpmn_unreachable_node" not in {f.code for f in findings}
    assert next(e for e in m.elements if e.id == "Floating").tier == "documented"
