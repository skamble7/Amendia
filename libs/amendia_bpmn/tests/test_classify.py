"""ADR-027 Phase 0 — the parser classifies (retains + tiers) instead of rejecting."""
from amendia_bpmn import ClassifiedElement, parse, select_process_id
from amendia_bpmn.model import RECOGNIZED_NON_EXECUTABLE

_HDR = '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
_FTR = "</bpmn:definitions>"


def _proc(*inner: str, pid: str = "P", executable: str = "true") -> str:
    return f'{_HDR}<bpmn:process id="{pid}" isExecutable="{executable}">{"".join(inner)}{"</bpmn:process>"}{_FTR}'


# A minimal, structurally-valid executable process: start → serviceTask → end.
_START = '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
_TASK = '<bpmn:serviceTask id="T1"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
_END = '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
_F1 = '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T1"/>'
_F2 = '<bpmn:sequenceFlow id="f2" sourceRef="T1" targetRef="E"/>'
_CORE = (_START, _TASK, _END, _F1, _F2)


def _errors(findings):
    return [f for f in findings if f.severity == "error"]


def test_seed_like_executable_parses_clean_all_executable():
    model, findings = parse(_proc(*_CORE), "P")
    assert model is not None
    assert _errors(findings) == []
    tiers = {e.id: e.tier for e in model.elements}
    assert tiers == {"S": "executable", "T1": "executable", "E": "executable"}
    assert model.coverage()["counts"] == {"executable": 3, "documented": 0, "unknown": 0}


def test_documented_element_retained_as_warning_not_error():
    # An off-path lane set + boundary event + data object: recognized BPMN, not executable.
    docs = '<bpmn:laneSet id="LS"><bpmn:lane id="L1"/></bpmn:laneSet>' \
           '<bpmn:boundaryEvent id="B1" attachedToRef="T1"/>' \
           '<bpmn:dataObject id="DO"/>'
    model, findings = parse(_proc(docs, *_CORE), "P")
    assert model is not None
    assert _errors(findings) == []  # documented elements never hard-error
    # The parser walks only direct children of <process>, so laneSet (not the nested lane) is seen.
    by_kind = {e.kind: e for e in model.elements}
    for kind in ("laneSet", "boundaryEvent", "dataObject"):
        assert by_kind[kind].tier == "documented", kind
        assert kind in RECOGNIZED_NON_EXECUTABLE
    docwarn = [f for f in findings if f.code == "bpmn_documented_element"]
    assert docwarn and all(f.severity == "warning" for f in docwarn)


def test_unknown_element_retained_as_info():
    model, findings = parse(_proc('<bpmn:fooBar id="X1"/>', *_CORE), "P")
    assert model is not None
    assert _errors(findings) == []
    x = next(e for e in model.elements if e.kind == "fooBar")
    assert x.tier == "unknown"
    info = [f for f in findings if f.code == "bpmn_unknown_element"]
    assert info and all(f.severity == "info" for f in info)


def test_parallel_gateway_is_documented_but_retained_in_typed_collection():
    # parallelGateway: recognized NODE_KIND (compiler still rejects it) but NOT executable.
    pg = '<bpmn:parallelGateway id="GW"><bpmn:incoming>f2</bpmn:incoming></bpmn:parallelGateway>'
    model, findings = parse(_proc(*_CORE, pg), "P")
    assert model is not None
    assert "GW" in model.parallel_gateways          # still visible to the compiler's rejection
    gw = next(e for e in model.elements if e.id == "GW")
    assert gw.tier == "documented"                   # but classified documented for coverage


def test_off_path_documented_element_does_not_trip_reachability():
    docs = '<bpmn:laneSet id="LS"/><bpmn:textAnnotation id="TA"/>'
    _, findings = parse(_proc(docs, *_CORE), "P")
    codes = {f.code for f in findings}
    assert "bpmn_unreachable_node" not in codes
    assert "bpmn_no_path_to_end" not in codes


def test_on_path_documented_element_still_dangling_error():
    # A flow into a documented (non-node) element → dangling target → hard error (blocks activation).
    on_path = '<bpmn:dataObject id="M"/><bpmn:sequenceFlow id="f3" sourceRef="T1" targetRef="M"/>'
    _, findings = parse(_proc(*_CORE, on_path), "P")
    dangling = [f for f in findings if f.code == "bpmn_dangling_flow"]
    assert dangling and all(f.severity == "error" for f in dangling)


def test_coverage_counts():
    docs = '<bpmn:laneSet id="LS"/><bpmn:fooBar id="X"/>'
    model, _ = parse(_proc(docs, *_CORE), "P")
    assert model.coverage()["counts"] == {"executable": 3, "documented": 1, "unknown": 1}


def test_select_process_id_prefers_executable():
    xml = (f'{_HDR}<bpmn:process id="Doc" isExecutable="false"/>'
           f'<bpmn:process id="Exec" isExecutable="true"/>{_FTR}')
    assert select_process_id(xml) == "Exec"
    # both paths agree: the selected id is the one parse resolves
    model, _ = parse(_proc(*_CORE, pid="Exec"), select_process_id(_proc(*_CORE, pid="Exec")))
    assert model is not None and model.process_id == "Exec"


def test_classified_element_shape():
    assert ClassifiedElement(id="x", kind="task", tier="documented").tier == "documented"
