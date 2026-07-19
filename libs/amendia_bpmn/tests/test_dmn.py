"""ADR-037 — native DMN decision tables: bounded FEEL unary tests, hit policies, table validation."""
import pytest

from amendia_bpmn import DecisionTable, evaluate_decision, parse_decision_table, validate_table
from amendia_bpmn.dmn import (
    DecisionEvaluationError,
    DmnError,
    parse_unary_test,
    _test_matches,
)


def _table(inputs, outputs, rules, hit_policy="UNIQUE"):
    return parse_decision_table({
        "hit_policy": hit_policy,
        "inputs": [{"expression": e} for e in inputs],
        "outputs": [(o if isinstance(o, dict) else {"name": o}) for o in outputs],
        "rules": rules,
    })


# --------------------------------------------------------------------------- #
# Bounded unary tests
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cell,value,expected", [
    ('-', "anything", True),                       # dash = irrelevant
    ('"PADDED"', "PADDED", True),
    ('"PADDED"', "OTHER", False),
    ('42', 42, True),
    ('42', 43, False),
    ('true', True, True),
    ('true', False, False),
    ('< 10', 5, True), ('< 10', 10, False),
    ('<= 10', 10, True),
    ('> 10', 11, True), ('> 10', 10, False),
    ('>= 10', 10, True),
    ('= 7', 7, True), ('= 7', 8, False),
    ('[1..10]', 1, True), ('[1..10]', 10, True), ('[1..10]', 11, False),
    ('(1..10]', 1, False), ('(1..10]', 10, True),
    ('[1..10)', 10, False), ('[1..10)', 1, True),
    ('(1..10)', 1, False), ('(1..10)', 10, False), ('(1..10)', 5, True),
    ('"A","B"', "B", True), ('"A","B"', "C", False),
    ('1,2,3', 2, True), ('1,2,3', 4, False),
    ('not("A")', "B", True), ('not("A")', "A", False),
    ('not(1,2)', 3, True), ('not(1,2)', 2, False),
])
def test_unary_test_forms(cell, value, expected):
    assert _test_matches(parse_unary_test(cell), value) is expected


def test_comparison_on_non_numeric_is_false_not_error():
    assert _test_matches(parse_unary_test("> 10"), "abc") is False


@pytest.mark.parametrize("bad", ['PADDED', 'foo bar', '~= 3', '[1..]', 'in [1,2]'])
def test_bad_unary_test_rejected(bad):
    with pytest.raises(DmnError):
        parse_unary_test(bad)


# --------------------------------------------------------------------------- #
# Hit policies
# --------------------------------------------------------------------------- #
def test_unique_single_match():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['"a"'], "then": ["A"]},
        {"when": ['"b"'], "then": ["B"]},
    ])
    assert evaluate_decision(t, {"x": {"v": "b"}}) == {"verdict": "B"}


def test_unique_multi_match_is_runtime_error():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["A"]},
        {"when": ['"b"'], "then": ["B"]},
    ])
    with pytest.raises(DecisionEvaluationError):
        evaluate_decision(t, {"x": {"v": "b"}})


def test_first_takes_first_in_order():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["catch"]},
        {"when": ['"b"'], "then": ["specific"]},
    ], hit_policy="FIRST")
    assert evaluate_decision(t, {"x": {"v": "b"}}) == {"verdict": "catch"}


def test_priority_by_output_order():
    t = parse_decision_table({
        "hit_policy": "PRIORITY",
        "inputs": [{"expression": "x.v"}],
        "outputs": [{"name": "verdict", "priority_order": ["reject", "review", "accept"]}],
        "rules": [
            {"when": ['-'], "then": ["accept"]},
            {"when": ['"b"'], "then": ["reject"]},
        ],
    })
    assert evaluate_decision(t, {"x": {"v": "b"}}) == {"verdict": "reject"}  # reject ranks highest


def test_any_same_output_ok_conflict_errors():
    ok = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["A"]},
        {"when": ['"b"'], "then": ["A"]},
    ], hit_policy="ANY")
    assert evaluate_decision(ok, {"x": {"v": "b"}}) == {"verdict": "A"}
    conflict = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["A"]},
        {"when": ['"b"'], "then": ["B"]},
    ], hit_policy="ANY")
    with pytest.raises(DecisionEvaluationError):
        evaluate_decision(conflict, {"x": {"v": "b"}})


def test_collect_returns_list():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["A"]},
        {"when": ['"b"'], "then": ["B"]},
    ], hit_policy="COLLECT")
    assert evaluate_decision(t, {"x": {"v": "b"}}) == [{"verdict": "A"}, {"verdict": "B"}]
    assert evaluate_decision(t, {"x": {"v": "z"}}) == [{"verdict": "A"}]  # only the catch-all


def test_no_match_single_hit_is_error():
    t = _table(["x.v"], ["verdict"], [{"when": ['"a"'], "then": ["A"]}], hit_policy="FIRST")
    with pytest.raises(DecisionEvaluationError):
        evaluate_decision(t, {"x": {"v": "z"}})


def test_multi_input_and_field_dotpath():
    t = _table(["f.tier", "f.amount"], ["verdict"], [
        {"when": ['"high"', '-'], "then": ["review"]},
        {"when": ['"low"', '< 1000'], "then": ["auto"]},
        {"when": ['-', '-'], "then": ["review"]},
    ], hit_policy="FIRST")
    assert evaluate_decision(t, {"f": {"tier": "low", "amount": 500}}) == {"verdict": "auto"}
    assert evaluate_decision(t, {"f": {"tier": "high", "amount": 500}}) == {"verdict": "review"}


# --------------------------------------------------------------------------- #
# DMN XML parse
# --------------------------------------------------------------------------- #
def test_parse_dmn_xml():
    xml = """<?xml version="1.0"?>
    <definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/">
      <decision id="d" name="Repair"><decisionTable hitPolicy="FIRST">
        <input label="tier"><inputExpression typeRef="string"><text>f.tier</text></inputExpression></input>
        <output name="verdict" typeRef="string"/>
        <rule><inputEntry><text>"high"</text></inputEntry><outputEntry><text>"review"</text></outputEntry></rule>
        <rule><inputEntry><text>-</text></inputEntry><outputEntry><text>"auto"</text></outputEntry></rule>
      </decisionTable></decision>
    </definitions>"""
    t = parse_decision_table(xml)
    assert t.hit_policy == "FIRST"
    assert t.inputs[0].expression == "f.tier"
    assert t.outputs[0].name == "verdict"
    assert evaluate_decision(t, {"f": {"tier": "high"}}) == {"verdict": "review"}
    assert evaluate_decision(t, {"f": {"tier": "low"}}) == {"verdict": "auto"}


# --------------------------------------------------------------------------- #
# Table validation
# --------------------------------------------------------------------------- #
def _codes(t):
    return {f.code for f in validate_table(t)}


def test_validate_ok_table():
    t = _table(["x.v"], ["verdict"], [{"when": ['"a"'], "then": ["A"]}])
    assert validate_table(t) == []


def test_validate_unknown_hit_policy():
    t = _table(["x.v"], ["verdict"], [{"when": ['"a"'], "then": ["A"]}], hit_policy="RANDOM")
    assert "dmn_unknown_hit_policy" in _codes(t)


def test_validate_malformed_no_rules_and_arity():
    assert "dmn_table_malformed" in _codes(_table(["x.v"], ["verdict"], []))
    # a rule with the wrong number of input cells
    bad = _table(["x.v", "x.w"], ["verdict"], [{"when": ['"a"'], "then": ["A"]}])
    assert "dmn_table_malformed" in _codes(bad)


def test_validate_bad_unary_test():
    t = _table(["x.v"], ["verdict"], [{"when": ['PADDED'], "then": ["A"]}])  # unquoted string
    assert "dmn_bad_unary_test" in _codes(t)


def test_validate_priority_requires_order():
    t = _table(["x.v"], [{"name": "verdict"}], [{"when": ['-'], "then": ["A"]}], hit_policy="PRIORITY")
    assert "dmn_table_malformed" in _codes(t)


def test_validate_static_overlap_unique():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['[1..10]'], "then": ["A"]},
        {"when": ['[5..15]'], "then": ["B"]},
    ])
    assert "dmn_rules_overlap" in _codes(t)


def test_validate_disjoint_ranges_no_overlap():
    t = _table(["x.v"], ["verdict"], [
        {"when": ['[1..10]'], "then": ["A"]},
        {"when": ['[20..30]'], "then": ["B"]},
    ])
    assert "dmn_rules_overlap" not in _codes(t)


def test_validate_any_same_output_not_flagged():
    # ANY with overlapping rules that AGREE on output is allowed (not an overlap error).
    t = _table(["x.v"], ["verdict"], [
        {"when": ['-'], "then": ["A"]},
        {"when": ['"b"'], "then": ["A"]},
    ], hit_policy="ANY")
    assert "dmn_rules_overlap" not in _codes(t)
