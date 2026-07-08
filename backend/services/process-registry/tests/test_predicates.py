# tests/test_predicates.py
import pytest

from app.validation.predicates import PredicateSyntaxError, check_predicate, evaluate

ENV = {
    "exception_type": "unable_to_apply",
    "payment": {"msg_type": "pacs.008.001.10", "amount": 250000},
    "reason_codes": ["AC01", "BE04"],
    "value_date": "2026-07-05",
}


@pytest.mark.parametrize("pred,expected", [
    ({"field": "exception_type", "op": "eq", "value": "unable_to_apply"}, True),
    ({"field": "exception_type", "op": "ne", "value": "returned"}, True),
    ({"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"}, True),
    ({"field": "payment.msg_type", "op": "starts_with", "value": "pacs.004"}, False),
    ({"field": "reason_codes", "op": "intersects", "value": ["AC01", "RC01"]}, True),
    ({"field": "reason_codes", "op": "intersects", "value": ["ZZ99"]}, False),
    ({"field": "exception_type", "op": "in", "value": ["a", "unable_to_apply"]}, True),
    ({"field": "payment.amount", "op": "gt", "value": 100000}, True),
    ({"field": "payment.amount", "op": "lte", "value": 250000}, True),
    ({"field": "payment.amount", "op": "lt", "value": 100000}, False),
    ({"field": "value_date", "op": "gte", "value": "2026-07-01"}, True),
    ({"field": "payment.missing", "op": "exists"}, False),
    ({"field": "payment.msg_type", "op": "exists"}, True),
    ({"field": "nope.deep", "op": "eq", "value": 1}, False),  # missing path → false
])
def test_leaf_ops(pred, expected):
    assert evaluate(pred, ENV) is expected


def test_combinators():
    assert evaluate({"all": [
        {"field": "exception_type", "op": "eq", "value": "unable_to_apply"},
        {"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"},
    ]}, ENV) is True
    assert evaluate({"any": [
        {"field": "exception_type", "op": "eq", "value": "returned"},
        {"field": "reason_codes", "op": "intersects", "value": ["AC01"]},
    ]}, ENV) is True
    assert evaluate({"not": {"field": "exception_type", "op": "eq", "value": "returned"}}, ENV) is True


WIRE_RULE = {"all": [
    {"field": "exception_type", "op": "eq", "value": "unable_to_apply"},
    {"field": "payment.msg_type", "op": "starts_with", "value": "pacs.008"},
    {"field": "reason_codes", "op": "intersects", "value": ["AC01", "AC04", "RC01", "BE04"]},
]}


def test_wire_rule_matches_sample_and_not_mutated():
    assert evaluate(WIRE_RULE, ENV) is True
    mutated = {**ENV, "reason_codes": ["ZZ99"]}
    assert evaluate(WIRE_RULE, mutated) is False


def test_check_predicate_rejects_bad():
    with pytest.raises(PredicateSyntaxError):
        check_predicate({"field": "x", "op": "not_an_op"})
    with pytest.raises(PredicateSyntaxError):
        check_predicate({"all": []})
    with pytest.raises(PredicateSyntaxError):
        check_predicate({"weird": 1})
    check_predicate(WIRE_RULE)  # valid → no raise
