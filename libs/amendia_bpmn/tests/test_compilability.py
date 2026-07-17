"""ADR-027 §1a / Phase 2.5 — the shared structural executable-subset gate + profile hierarchy."""
from amendia_bpmn import EXECUTION_PROFILES, compilability_findings, parse, profile_rank, required_profile

_HDR = '<?xml version="1.0"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
_FTR = "</bpmn:definitions>"


def _proc(inner: str) -> str:
    return f'{_HDR}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


_CORE = (
    '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
    '<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
    '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
    '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>'
    '<bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="E"/>'
)


def _codes(model):
    return {f.code for f in compilability_findings(model)}


def test_clean_executable_has_no_compilability_findings():
    model, _ = parse(_proc(_CORE), "P")
    assert compilability_findings(model) == []


def test_parallel_gateway_is_a_compilability_error():
    pg = ('<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
          '<bpmn:parallelGateway id="GW"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>fa</bpmn:outgoing><bpmn:outgoing>fb</bpmn:outgoing></bpmn:parallelGateway>'
          '<bpmn:endEvent id="ea"><bpmn:incoming>fa</bpmn:incoming></bpmn:endEvent>'
          '<bpmn:endEvent id="eb"><bpmn:incoming>fb</bpmn:incoming></bpmn:endEvent>'
          '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="GW"/>'
          '<bpmn:sequenceFlow id="fa" sourceRef="GW" targetRef="ea"/>'
          '<bpmn:sequenceFlow id="fb" sourceRef="GW" targetRef="eb"/>')
    model, _ = parse(_proc(pg), "P")
    fs = compilability_findings(model)
    assert "bpmn_parallel_gateway_unsupported" in {f.code for f in fs}
    assert all(f.severity == "error" for f in fs)


def test_chained_gateway_is_a_compilability_error():
    chained = ('<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
               '<bpmn:exclusiveGateway id="G1"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:exclusiveGateway>'
               '<bpmn:exclusiveGateway id="G2"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:exclusiveGateway>'
               '<bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
               '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="G1"/>'
               '<bpmn:sequenceFlow id="f2" sourceRef="G1" targetRef="G2"/>'
               '<bpmn:sequenceFlow id="f3" sourceRef="G2" targetRef="E"/>')
    model, _ = parse(_proc(chained), "P")
    assert "bpmn_chained_gateway_unsupported" in _codes(model)


def test_parallel_profile_allows_well_formed_fork_join():
    # ADR-027 Phase 2.1/2.5: a well-formed fork/join is NOT a compilability error under the
    # "parallel" profile; the default profile still refuses parallel gateways wholesale.
    model, _ = parse(_fork_join(), "P", profile="parallel")
    assert compilability_findings(model, profile="parallel") == []
    assert "bpmn_parallel_gateway_unsupported" in _codes(model)  # default profile still refuses
    # under the parallel profile, the parser classifies the gateways executable (coverage)
    assert next(e for e in model.elements if e.id == "Fork").tier == "executable"


def _fork_join(branches_ok=True, *, unbalanced=False, nested=False, interleaved=False):
    """A start → fork → (A ∥ B) → join → end region, with knobs to make it malformed."""
    inner = ['<bpmn:startEvent id="S"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>',
             '<bpmn:parallelGateway id="Fork"/>',
             '<bpmn:serviceTask id="A"/>', '<bpmn:serviceTask id="B"/>',
             '<bpmn:endEvent id="E"/>',
             '<bpmn:sequenceFlow id="f0" sourceRef="S" targetRef="Fork"/>',
             '<bpmn:sequenceFlow id="fa" sourceRef="Fork" targetRef="A"/>',
             '<bpmn:sequenceFlow id="fb" sourceRef="Fork" targetRef="B"/>']
    if unbalanced:  # no join — branches both go to end (unmatched fork)
        inner += ['<bpmn:sequenceFlow id="ja" sourceRef="A" targetRef="E"/>',
                  '<bpmn:sequenceFlow id="jb" sourceRef="B" targetRef="E"/>']
    elif nested:  # branch A contains a nested fork
        inner += ['<bpmn:parallelGateway id="Fork2"/>', '<bpmn:parallelGateway id="Join"/>',
                  '<bpmn:serviceTask id="C"/>',
                  '<bpmn:sequenceFlow id="a_fork2" sourceRef="A" targetRef="Fork2"/>',
                  '<bpmn:sequenceFlow id="f2c" sourceRef="Fork2" targetRef="C"/>',
                  '<bpmn:sequenceFlow id="f2j" sourceRef="Fork2" targetRef="Join"/>',
                  '<bpmn:sequenceFlow id="cj" sourceRef="C" targetRef="Join"/>',
                  '<bpmn:sequenceFlow id="bj" sourceRef="B" targetRef="Join"/>',
                  '<bpmn:sequenceFlow id="je" sourceRef="Join" targetRef="E"/>']
    else:  # well-formed: A,B → Join → E
        inner += ['<bpmn:parallelGateway id="Join"/>',
                  '<bpmn:sequenceFlow id="aj" sourceRef="A" targetRef="Join"/>',
                  '<bpmn:sequenceFlow id="bj" sourceRef="B" targetRef="Join"/>',
                  '<bpmn:sequenceFlow id="je" sourceRef="Join" targetRef="E"/>']
    return _proc("".join(inner))


def test_profile_rank_and_hierarchy():
    # ADR-034 Phase 2.8: two spec levels; retired granular names normalize to common_executable.
    assert EXECUTION_PROFILES == ["common_subset", "common_executable"]
    assert profile_rank("common_subset") == 0 and profile_rank("common_executable") == 1
    assert profile_rank("parallel") == profile_rank("timers") == 1  # retired → common_executable
    import pytest
    with pytest.raises(ValueError):
        profile_rank("nope")


def test_required_profile_derived_from_bpmn():
    model, _ = parse(_proc(_CORE), "P")
    assert required_profile(model) == "common_subset"
    model, _ = parse(_fork_join(), "P", profile="common_executable")
    assert required_profile(model) == "common_executable"


def test_wellformed_fork_join_passes_under_parallel():
    model, _ = parse(_fork_join(), "P", profile="parallel")
    assert compilability_findings(model, profile="parallel") == []


def test_unbalanced_fork_without_join_errors():
    model, _ = parse(_fork_join(unbalanced=True), "P", profile="parallel")
    assert "bpmn_parallel_unbalanced" in _codes_profile(model)


def test_nested_parallel_rejected():
    model, _ = parse(_fork_join(nested=True), "P", profile="parallel")
    assert "bpmn_parallel_nested_unsupported" in _codes_profile(model)


def _codes_profile(model):
    return {f.code for f in compilability_findings(model, profile="parallel")}


def test_task_multi_outgoing_is_a_compilability_error():
    multi = ('<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
             '<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing><bpmn:outgoing>f3</bpmn:outgoing></bpmn:serviceTask>'
             '<bpmn:endEvent id="E1"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
             '<bpmn:endEvent id="E2"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
             '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>'
             '<bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="E1"/>'
             '<bpmn:sequenceFlow id="f3" sourceRef="T" targetRef="E2"/>')
    model, _ = parse(_proc(multi), "P")
    assert "bpmn_task_outgoing_arity" in _codes(model)
