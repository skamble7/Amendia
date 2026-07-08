# app/engine/expr.py
"""Gateway condition expression subset.

Supported forms (whitespace-tolerant; both ``=`` and ``==`` accepted):
    <dotpath> = "literal"
    <dotpath> != "literal"

The dot-path is resolved against ``state.artifacts`` — its first segment is the
artifact name (per the manifest ``gateway_variables``), e.g.
``beneficiary.repair_verdict`` → ``artifacts["beneficiary"]["repair_verdict"]``.
Anything else raises ``ConditionSyntaxError`` (the compiler surfaces it with the
gateway id).
"""
from __future__ import annotations

import re
from typing import Any, Dict

_COND = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*(==|=|!=)\s*"([^"]*)"\s*$')


class ConditionSyntaxError(ValueError):
    """The gateway flow condition is outside the supported subset."""


def parse_condition(expr: str):
    """Return ``(segments, op, literal)`` where op is ``==`` or ``!=``."""
    m = _COND.match(expr or "")
    if not m:
        raise ConditionSyntaxError(f"unsupported gateway condition expression: {expr!r}")
    path, op, literal = m.group(1), m.group(2), m.group(3)
    return path.split("."), ("!=" if op == "!=" else "=="), literal


def resolve_path(segments, artifacts: Dict[str, Any]) -> Any:
    cur: Any = artifacts
    for seg in segments:
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def evaluate(expr: str, artifacts: Dict[str, Any]) -> bool:
    """Evaluate a supported condition against ``artifacts``."""
    segments, op, literal = parse_condition(expr)
    value = resolve_path(segments, artifacts)
    return (value == literal) if op == "==" else (value != literal)
