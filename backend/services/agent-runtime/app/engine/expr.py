# app/engine/expr.py
"""Gateway condition expression subset — runtime evaluation.

The *grammar* (the accepted syntax + parser) is the shared source of truth in
``amendia_bpmn.conditions`` — process-registry validates against the SAME module, so design time and runtime
can never drift. This file delegates parsing to it and keeps only the runtime concern: resolving the dotpath
against ``state.artifacts`` and comparing.

Supported forms (whitespace-tolerant; both ``=`` and ``==`` accepted):
    <dotpath> = "literal"
    <dotpath> != "literal"

The dot-path is resolved against ``state.artifacts`` — its first segment is the artifact name (per the manifest
``gateway_variables``), e.g. ``result.status`` → ``artifacts["result"]["status"]``. Anything else raises
``ConditionSyntaxError`` (the compiler surfaces it with the gateway id).
"""
from __future__ import annotations

from typing import Any, Dict

# Delegate the grammar to the shared module (single source of truth; no local regex copy → no drift).
from amendia_bpmn.conditions import CONDITION_RE as _COND  # noqa: F401 - re-exported for back-compat
from amendia_bpmn.conditions import ConditionSyntaxError, parse_condition

__all__ = ["ConditionSyntaxError", "parse_condition", "resolve_path", "evaluate"]


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
