# tests/test_conditions.py
"""The shared gateway-condition grammar: parse (runtime arbiter), Tier-1 lossless normalization, and the
Tier-2 error classification. This is the single source of truth both agent-runtime and process-registry use."""
from __future__ import annotations

import pytest

from amendia_bpmn.conditions import (
    ConditionSyntaxError,
    classify_condition_error,
    condition_lhs,
    normalize_condition,
    parse_condition,
)


# --- parse (unchanged runtime grammar) --------------------------------------------------------------
def test_parse_canonical_forms():
    assert parse_condition('decision.rbo_decision = "approve"') == (["decision", "rbo_decision"], "==", "approve")
    assert parse_condition('a == "x"') == (["a"], "==", "x")
    assert parse_condition('a.b.c != "y"') == (["a", "b", "c"], "!=", "y")


@pytest.mark.parametrize("bad", ['limit_breached = true', 'a > "x"', 'decision', '${x}', "x = 'y'"])
def test_parse_rejects_non_canonical(bad):
    with pytest.raises(ConditionSyntaxError):
        parse_condition(bad)


# --- Tier-1 normalization (lossless only) -----------------------------------------------------------
def test_golden_normalizes_to_itself():
    raw = 'decision.rbo_decision = "approve"'
    assert normalize_condition(raw) == (raw, [])            # zero behavior change for existing valid packs


def test_camunda_dollar_wrapper_is_unwrapped():
    canon, changes = normalize_condition('${decision == "Proceed"}')
    assert canon == 'decision == "Proceed"' and changes == ["unwrapped ${…} expression"]
    parse_condition(canon)                                  # now parses


def test_hash_wrapper_is_unwrapped():
    canon, changes = normalize_condition('#{ beneficiary.repair_verdict != "unrepairable" }')
    assert canon == 'beneficiary.repair_verdict != "unrepairable"' and changes == ["unwrapped #{…} expression"]


def test_single_quotes_become_double():
    canon, changes = normalize_condition("x = 'approve'")
    assert canon == 'x = "approve"' and changes == ["converted single-quoted literal to double-quoted"]


def test_normalization_is_idempotent():
    once, _ = normalize_condition('${x = \'y\'}')
    twice, ch2 = normalize_condition(once)
    assert once == 'x = "y"' and twice == once and ch2 == []


def test_ambiguous_is_left_untouched_not_mis_rewritten():
    # a literal containing a double-quote → converting the single quotes would be lossy → leave it
    assert normalize_condition('x = \'a"b\'') == ('x = \'a"b\'', [])
    # unbalanced / multiple wrappers → not one whole-body wrapper → leave it
    assert normalize_condition('${a} and ${b}') == ('${a} and ${b}', [])
    # multiple single-quoted parts → ambiguous → leave it
    assert normalize_condition("a = 'x' or b = 'y'") == ("a = 'x' or b = 'y'", [])


# --- Tier-2 classification --------------------------------------------------------------------------
def test_classify_reasons():
    assert classify_condition_error('limit_breached = true') == "unquoted_rhs"
    assert classify_condition_error('amount > 5') == "unsupported_operator"
    assert classify_condition_error('a and b') == "unsupported_operator"
    assert classify_condition_error('${a} and ${b}') == "wrapper_unresolved"
    assert classify_condition_error('x = "a"b"') == "not_parseable"


def test_condition_lhs():
    assert condition_lhs('decision.rbo_decision = "approve"') == "decision.rbo_decision"
    assert condition_lhs('limit_breached = true') == "limit_breached"
    assert condition_lhs('  ') is None
