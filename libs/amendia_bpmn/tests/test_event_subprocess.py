"""ADR-042 / Item F — event sub-process (triggeredByEvent="true"): a scope-wide interrupting error/
timer handler. Parsed into ``event_subprocesses`` + registered onto its enclosing scope's boundary map
(reusing ADR-041's router); the enclosing scope may be the whole process. Message/signal/escalation
and non-interrupting starts are refused; two handlers of the same trigger on one scope are ambiguous.
"""
from amendia_bpmn import compilability_findings, parse, required_profile

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">')
_FTR = "</bpmn:definitions>"


def _doc(inner: str, defs: str = "") -> str:
    return f'{_HDR}{defs}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


# start → T1 → End_Done, plus an event sub-process whose body is eS(trigger) → H1 → eEnd.
def _proc(esp: str, defs: str = "") -> str:
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="T1"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T1"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="T1" targetRef="End_Done"/>'
        + esp)
    return _doc(inner, defs)


def _esp(esp_id, start_xml, *, hid, first_flow, second_flow, end_id):
    """An event sub-process: <start_xml> → hid → end_id."""
    return (
        f'<bpmn:subProcess id="{esp_id}" triggeredByEvent="true">'
        f'{start_xml}'
        f'<bpmn:serviceTask id="{hid}"><bpmn:incoming>{first_flow}</bpmn:incoming><bpmn:outgoing>{second_flow}</bpmn:outgoing></bpmn:serviceTask>'
        f'<bpmn:endEvent id="{end_id}"><bpmn:incoming>{second_flow}</bpmn:incoming></bpmn:endEvent>'
        f'<bpmn:sequenceFlow id="{first_flow}" sourceRef="{esp_id}_S" targetRef="{hid}"/>'
        f'<bpmn:sequenceFlow id="{second_flow}" sourceRef="{hid}" targetRef="{end_id}"/>'
        f'</bpmn:subProcess>')


def _err_start(esp_id, ref=None):
    r = f' errorRef="{ref}"' if ref else ""
    return f'<bpmn:startEvent id="{esp_id}_S"><bpmn:errorEventDefinition{r}/><bpmn:outgoing>{esp_id}_a</bpmn:outgoing></bpmn:startEvent>'


def _timer_start(esp_id, dur="PT2H"):
    return (f'<bpmn:startEvent id="{esp_id}_S"><bpmn:timerEventDefinition>'
            f'<bpmn:timeDuration>{dur}</bpmn:timeDuration></bpmn:timerEventDefinition>'
            f'<bpmn:outgoing>{esp_id}_a</bpmn:outgoing></bpmn:startEvent>')


def _codes(model, profile="common_executable"):
    return {f.code for f in compilability_findings(model, profile=profile)}


def _errcodes(findings):
    return {f.code for f in findings if f.severity == "error"}


# --- process-level error event sub-process -------------------------------------------------------

def test_process_level_error_esp_registered_on_process_scope():
    xml = _proc(
        _esp("ESP", _err_start("ESP", "ErrHit"), hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"),
        defs='<bpmn:error id="ErrHit" errorCode="screening.hit"/>')
    m, findings = parse(xml, "P", profile="common_executable")
    assert _errcodes(findings) == set(), _errcodes(findings)
    esp = m.event_subprocesses["ESP"]
    assert esp.trigger == "error" and esp.error_code == "screening.hit"
    assert esp.enclosing_scope == "P" and esp.body_start_successor == "H1" and esp.end_ids == ["eEnd"]
    # registered onto the PROCESS scope's error map — a scope-wide error handler
    ebs = m.error_boundaries.get("P", [])
    assert [e.id for e in ebs] == ["ESP"] and ebs[0].error_code == "screening.hit" and ebs[0].target == "H1"
    # the container is not on any flow (not bindable) but the body task IS a bound node
    assert "ESP" not in m.bindable_elements() and m.bindable_elements()["H1"] == "serviceTask"
    assert required_profile(m) == "common_executable"
    assert _codes(m) == set()


def test_catch_all_error_esp_has_no_code():
    xml = _proc(_esp("ESP", _err_start("ESP"), hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"))
    m, findings = parse(xml, "P", profile="common_executable")
    assert _errcodes(findings) == set()
    assert m.event_subprocesses["ESP"].error_code is None  # catch-all (no errorRef)
    assert m.error_boundaries["P"][0].error_code is None


def test_esp_body_nodes_not_falsely_unreachable():
    xml = _proc(_esp("ESP", _err_start("ESP"), hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"))
    _m, findings = parse(xml, "P", profile="common_executable")
    codes = {f.code for f in findings}
    assert "bpmn_unreachable_node" not in codes and "bpmn_no_path_to_end" not in codes
    assert "bpmn_subprocess_arity" not in codes  # an ESP is not a flattened box → no in/out arity


# --- timer event sub-process ---------------------------------------------------------------------

def test_process_level_timer_esp_allowed():
    xml = _proc(_esp("ESP", _timer_start("ESP"), hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"))
    m, findings = parse(xml, "P", profile="common_executable")
    assert _errcodes(findings) == set()
    esp = m.event_subprocesses["ESP"]
    assert esp.trigger == "timer" and esp.timer.value == "PT2H" and esp.enclosing_scope == "P"
    # registered as a scope-wide SLA on the PROCESS; the process-level host is explicitly allowed
    assert m.boundary_timers["P"].id == "ESP" and m.boundary_timers["P"].target == "H1"
    assert "bpmn_timer_boundary_host_unsupported" not in _codes(m)
    assert _codes(m) == set()


def test_subprocess_scoped_timer_esp_registered_on_subprocess():
    sub = (
        '<bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="Inner"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="Inner"/>'
        '<bpmn:sequenceFlow id="if2" sourceRef="Inner" targetRef="iE"/>'
        + _esp("ESP", _timer_start("ESP"), hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd") +
        '</bpmn:subProcess>')
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        + sub +
        '<bpmn:endEvent id="End_Done"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="End_Done"/>')
    m, findings = parse(_doc(inner), "P", profile="common_executable")
    assert _errcodes(findings) == set(), _errcodes(findings)
    esp = m.event_subprocesses["ESP"]
    assert esp.enclosing_scope == "Sub" and esp.trigger == "timer"
    assert m.boundary_timers["Sub"].id == "ESP" and m.boundary_timers["Sub"].target == "H1"
    assert _codes(m) == set()


# --- refusals ------------------------------------------------------------------------------------

def test_message_triggered_esp_refused():
    start = ('<bpmn:startEvent id="ESP_S"><bpmn:messageEventDefinition/>'
             '<bpmn:outgoing>ESP_a</bpmn:outgoing></bpmn:startEvent>')
    xml = _proc(_esp("ESP", start, hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"))
    m, findings = parse(xml, "P", profile="common_executable")
    assert m.event_subprocesses["ESP"].unsupported is not None
    assert "bpmn_event_subprocess_unsupported" in _codes(m)
    # not silently registered as a handler
    assert m.error_boundaries.get("P", []) == [] and "P" not in m.boundary_timers


def test_non_interrupting_esp_refused():
    start = ('<bpmn:startEvent id="ESP_S" isInterrupting="false"><bpmn:errorEventDefinition/>'
             '<bpmn:outgoing>ESP_a</bpmn:outgoing></bpmn:startEvent>')
    xml = _proc(_esp("ESP", start, hid="H1", first_flow="ESP_a", second_flow="ESP_b", end_id="eEnd"))
    m, _ = parse(xml, "P", profile="common_executable")
    assert m.event_subprocesses["ESP"].is_interrupting is False
    assert "bpmn_event_subprocess_unsupported" in _codes(m)


def test_two_timer_esps_on_one_scope_ambiguous():
    xml = _proc(
        _esp("ESP1", _timer_start("ESP1"), hid="H1", first_flow="ESP1_a", second_flow="ESP1_b", end_id="e1") +
        _esp("ESP2", _timer_start("ESP2"), hid="H2", first_flow="ESP2_a", second_flow="ESP2_b", end_id="e2"))
    m, _ = parse(xml, "P", profile="common_executable")
    assert "bpmn_event_subprocess_ambiguous" in _codes(m)


def test_two_error_esps_same_code_on_one_scope_ambiguous():
    xml = _proc(
        _esp("ESP1", _err_start("ESP1", "E"), hid="H1", first_flow="ESP1_a", second_flow="ESP1_b", end_id="e1") +
        _esp("ESP2", _err_start("ESP2", "E"), hid="H2", first_flow="ESP2_a", second_flow="ESP2_b", end_id="e2"),
        defs='<bpmn:error id="E" errorCode="dup.code"/>')
    m, _ = parse(xml, "P", profile="common_executable")
    assert "bpmn_event_subprocess_ambiguous" in _codes(m)


def test_two_error_esps_distinct_codes_ok():
    xml = _proc(
        _esp("ESP1", _err_start("ESP1", "E1"), hid="H1", first_flow="ESP1_a", second_flow="ESP1_b", end_id="e1") +
        _esp("ESP2", _err_start("ESP2", "E2"), hid="H2", first_flow="ESP2_a", second_flow="ESP2_b", end_id="e2"),
        defs='<bpmn:error id="E1" errorCode="c.one"/><bpmn:error id="E2" errorCode="c.two"/>')
    m, findings = parse(xml, "P", profile="common_executable")
    assert _errcodes(findings) == set()
    assert "bpmn_event_subprocess_ambiguous" not in _codes(m)
    assert {e.error_code for e in m.error_boundaries["P"]} == {"c.one", "c.two"}
