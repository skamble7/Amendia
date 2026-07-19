"""ADR-036 / Backlog #3 — multi-instance activities: parse, capture, tier, profile gate, refusals."""
from amendia_bpmn import (
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


def _mi_task(mi_inner: str, *, task="serviceTask", agg: str = "") -> str:
    """start → Screen (MI task) → End."""
    aggattr = f' amendia:aggregation="{agg}"' if agg else ""
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        f'<bpmn:{task} id="Screen"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        f'<bpmn:multiInstanceLoopCharacteristics{aggattr}>{mi_inner}'
        '</bpmn:multiInstanceLoopCharacteristics>'
        f'</bpmn:{task}>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Screen"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Screen" targetRef="E"/>'
    )
    return _doc(inner)


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


# --------------------------------------------------------------------------- #
# Parse / capture
# --------------------------------------------------------------------------- #
def test_parallel_cardinality_captured():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                 profile="common_executable")
    mi = m.multi_instance["Screen"]
    assert mi.is_sequential is False
    assert mi.cardinality == 3 and mi.collection_ref is None
    assert mi.aggregation == "list"  # default
    assert mi.on_subprocess is False


def test_sequential_collection_item_and_completion_captured():
    mi_inner = (
        '<bpmn:loopDataInputRef>parties</bpmn:loopDataInputRef>'
        '<bpmn:inputDataItem name="party"/>'
        '<bpmn:completionCondition>screening.verdict == "hit"</bpmn:completionCondition>'
    )
    doc = _mi_task(mi_inner).replace(
        "<bpmn:multiInstanceLoopCharacteristics",
        '<bpmn:multiInstanceLoopCharacteristics isSequential="true"')
    m, _ = parse(doc, "P", profile="common_executable")
    mi = m.multi_instance["Screen"]
    assert mi.is_sequential is True
    assert mi.collection_ref == "parties" and mi.item_name == "party"
    assert mi.completion_condition == 'screening.verdict == "hit"'
    assert mi.cardinality is None


def test_aggregation_extension_attribute_indexed():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>2</bpmn:loopCardinality>", agg="indexed"),
                 "P", profile="common_executable")
    assert m.multi_instance["Screen"].aggregation == "indexed"


def test_unknown_aggregation_defaults_to_list():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>2</bpmn:loopCardinality>", agg="bogus"),
                 "P", profile="common_executable")
    assert m.multi_instance["Screen"].aggregation == "list"


# --------------------------------------------------------------------------- #
# Profile gate / tier
# --------------------------------------------------------------------------- #
def test_required_profile_is_common_executable():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                 profile="common_executable")
    assert required_profile(m) == "common_executable"
    assert profile_rank("common_executable") > profile_rank("common_subset")


def test_refused_under_common_subset():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                 profile="common_subset")
    assert "bpmn_multi_instance_unsupported" in _codes(m, "common_subset")
    assert "Screen" in m.multi_instance  # captured regardless of profile


def test_wellformed_passes_under_common_executable():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                 profile="common_executable")
    assert compilability_findings(m, profile="common_executable") == []


def test_mi_task_tier_flips_by_profile():
    m, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                 profile="common_executable")
    assert next(e for e in m.elements if e.id == "Screen").tier == "executable"
    m2, _ = parse(_mi_task("<bpmn:loopCardinality>3</bpmn:loopCardinality>"), "P",
                  profile="common_subset")
    assert next(e for e in m2.elements if e.id == "Screen").tier == "documented"


# --------------------------------------------------------------------------- #
# Structure refusals
# --------------------------------------------------------------------------- #
def test_unbounded_missing_cardinality_and_collection():
    # an empty MI (no loopCardinality, no loopDataInputRef) → unbounded N.
    m, _ = parse(_mi_task(""), "P", profile="common_executable")
    assert "bpmn_multi_instance_unbounded" in _codes(m, "common_executable")


def test_mi_on_subprocess_refused():
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        '<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2</bpmn:loopCardinality>'
        '</bpmn:multiInstanceLoopCharacteristics>'
        '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="iT"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing></bpmn:serviceTask>'
        '<bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="iT"/>'
        '<bpmn:sequenceFlow id="if2" sourceRef="iT" targetRef="iE"/>'
        '</bpmn:subProcess>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/>'
    )
    m, _ = parse(_doc(inner), "P", profile="common_executable")
    assert m.multi_instance["Sub"].on_subprocess is True
    assert "bpmn_multi_instance_subprocess_unsupported" in _codes(m, "common_executable")


def test_nested_mi_refused():
    # an MI task inside an MI sub-process → nested (plus the sub-process refusal).
    inner = (
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:subProcess id="Sub"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>'
        '<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2</bpmn:loopCardinality>'
        '</bpmn:multiInstanceLoopCharacteristics>'
        '<bpmn:startEvent id="iS"><bpmn:outgoing>if1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="iT"><bpmn:incoming>if1</bpmn:incoming><bpmn:outgoing>if2</bpmn:outgoing>'
        '<bpmn:multiInstanceLoopCharacteristics><bpmn:loopCardinality>2</bpmn:loopCardinality>'
        '</bpmn:multiInstanceLoopCharacteristics>'
        '</bpmn:serviceTask>'
        '<bpmn:endEvent id="iE"><bpmn:incoming>if2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="if1" sourceRef="iS" targetRef="iT"/>'
        '<bpmn:sequenceFlow id="if2" sourceRef="iT" targetRef="iE"/>'
        '</bpmn:subProcess>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/>'
    )
    m, _ = parse(_doc(inner), "P", profile="common_executable")
    assert m.element_scope["iT"] == "Sub"
    assert "bpmn_multi_instance_nested_unsupported" in _codes(m, "common_executable")
