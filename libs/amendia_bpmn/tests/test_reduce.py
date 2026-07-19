"""ADR-038 — collection-reduction / summary evaluator: ops, empty-list semantics, item_path, validation."""
import pytest

from amendia_bpmn import (
    ReduceEvaluationError,
    evaluate_reduce,
    parse_reduce_config,
    validate_reduce,
)


def _cfg(**kw):
    return parse_reduce_config(kw)


def _run(inputs, **cfg):
    return evaluate_reduce(_cfg(**cfg), inputs)


# --------------------------------------------------------------------------- #
# Quantifiers
# --------------------------------------------------------------------------- #
def test_any_all_none_true_false():
    lst = [{"verdict": "hit"}, {"verdict": "clean"}]
    src = {"screening": lst}
    assert _run(src, op="any", source="screening", item_path="verdict", predicate='= "hit"',
                output_field="m") == {"m": True}
    assert _run(src, op="all", source="screening", item_path="verdict", predicate='= "hit"',
                output_field="m") == {"m": False}
    assert _run(src, op="none", source="screening", item_path="verdict", predicate='= "hit"',
                output_field="m") == {"m": False}
    clean = {"screening": [{"verdict": "clean"}, {"verdict": "clean"}]}
    assert _run(clean, op="any", source="screening", item_path="verdict", predicate='= "hit"',
                output_field="m") == {"m": False}
    assert _run(clean, op="none", source="screening", item_path="verdict", predicate='= "hit"',
                output_field="m") == {"m": True}


def test_quantifiers_empty_list_semantics():
    empty = {"s": []}
    assert _run(empty, op="any", source="s", item_path="v", predicate='= "x"')["result"] is False
    assert _run(empty, op="all", source="s", item_path="v", predicate='= "x"')["result"] is True
    assert _run(empty, op="none", source="s", item_path="v", predicate='= "x"')["result"] is True


# --------------------------------------------------------------------------- #
# count
# --------------------------------------------------------------------------- #
def test_count_matching_and_all():
    src = {"s": [{"v": "hit"}, {"v": "clean"}, {"v": "hit"}]}
    assert _run(src, op="count", source="s", item_path="v", predicate='= "hit"')["result"] == 2
    assert _run(src, op="count", source="s")["result"] == 3  # no predicate → all items


# --------------------------------------------------------------------------- #
# Numeric
# --------------------------------------------------------------------------- #
def test_numeric_sum_avg_min_max():
    src = {"s": [{"amt": 10}, {"amt": 20}, {"amt": 30}]}
    assert _run(src, op="sum", source="s", item_path="amt")["result"] == 60
    assert _run(src, op="avg", source="s", item_path="amt")["result"] == 20
    assert _run(src, op="min", source="s", item_path="amt")["result"] == 10
    assert _run(src, op="max", source="s", item_path="amt")["result"] == 30


def test_numeric_empty_list():
    empty = {"s": []}
    assert _run(empty, op="sum", source="s", item_path="amt")["result"] == 0
    assert _run(empty, op="avg", source="s", item_path="amt")["result"] == 0
    with pytest.raises(ReduceEvaluationError):
        _run(empty, op="min", source="s", item_path="amt")
    with pytest.raises(ReduceEvaluationError):
        _run(empty, op="max", source="s", item_path="amt")


def test_numeric_non_numeric_value_errors():
    with pytest.raises(ReduceEvaluationError):
        _run({"s": [{"amt": "oops"}]}, op="sum", source="s", item_path="amt")


# --------------------------------------------------------------------------- #
# Positional
# --------------------------------------------------------------------------- #
def test_first_last_with_and_without_predicate():
    src = {"s": [{"v": "clean"}, {"v": "hit"}, {"v": "clean"}, {"v": "hit"}]}
    assert _run(src, op="first", source="s", item_path="v", predicate='= "hit"')["result"] == "hit"
    assert _run(src, op="first", source="s", item_path="v")["result"] == "clean"   # raw first
    assert _run(src, op="last", source="s", item_path="v")["result"] == "hit"      # raw last
    # no match → None
    assert _run({"s": [{"v": "clean"}]}, op="first", source="s", item_path="v",
                predicate='= "hit"')["result"] is None


def test_first_without_item_path_returns_whole_item():
    src = {"s": [{"v": "a", "x": 1}, {"v": "b", "x": 2}]}
    assert _run(src, op="first", source="s")["result"] == {"v": "a", "x": 1}


# --------------------------------------------------------------------------- #
# source / item_path resolution
# --------------------------------------------------------------------------- #
def test_source_dotpath_and_sole_input():
    nested = {"dossier": {"parties": [{"v": "hit"}]}}
    assert _run(nested, op="any", source="dossier.parties", item_path="v", predicate='= "hit"')["result"] is True
    # "." with a single input = that input's value (the input artifact IS the list)
    assert _run({"only": [{"v": "hit"}]}, op="any", source=".", item_path="v", predicate='= "hit"')["result"] is True


def test_source_not_a_list_is_runtime_error():
    with pytest.raises(ReduceEvaluationError):
        _run({"s": {"not": "a list"}}, op="count", source="s")


def test_dot_source_ambiguous_with_multiple_inputs():
    with pytest.raises(ReduceEvaluationError):
        _run({"a": [], "b": []}, op="count", source=".")


# --------------------------------------------------------------------------- #
# Validation (config-only)
# --------------------------------------------------------------------------- #
def _codes(**kw):
    return {f.code for f in validate_reduce(_cfg(**kw))}


def test_validate_ok():
    assert validate_reduce(_cfg(op="any", source="s", item_path="v", predicate='= "hit"')) == []


def test_validate_unknown_op():
    assert "reduce_unknown_op" in _codes(op="frobnicate", source="s")


def test_validate_bad_predicate():
    assert "reduce_bad_predicate" in _codes(op="any", source="s", predicate="hit")  # unquoted


def test_validate_predicate_required():
    assert "reduce_predicate_required" in _codes(op="any", source="s")
    assert "reduce_predicate_required" in _codes(op="all", source="s")
    # count without a predicate is fine (counts all)
    assert "reduce_predicate_required" not in _codes(op="count", source="s")
