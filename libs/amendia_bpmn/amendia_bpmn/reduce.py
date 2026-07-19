# amendia_bpmn/reduce.py
"""Collection-reduction / summary capability evaluator (ADR-038).

Collapses a **list** input artifact into a scalar/summary value a gateway can branch on — the concrete
answer to the ADR-036/037 "any/all over a list" gap (`expr.py` gateway conditions and DMN unary tests
are scalar-only). Shared by the registry validator and the runtime — one implementation, like
`dmn.py`. The per-item predicate **reuses the bounded DMN unary-test surface** (`parse_unary_test` /
`_test_matches`) — one FEEL surface across the platform, no new mini-language. Pure over
`(config, inputs)` — deterministic, no clock, no I/O.

Ops:
  - quantifiers `any` / `all` / `none` (over `predicate`; empty list → `any=false`, `all=true`,
    `none=true` vacuously) → **boolean**
  - `count` (matching items if a predicate, else all items) → **int**
  - numeric `sum` / `min` / `max` / `avg` (over the `item_path` values; empty → `sum=0`/`avg=0`,
    `min`/`max` → a `reduce_numeric_empty` runtime error)
  - positional `first` / `last` (the matching item's `item_path` value, or the raw first/last if no
    predicate; empty/no-match → `None`)

Note: `any`/`all`/`none`/`count`/numeric yield **non-string** values. Gateways (`expr.py`) compare
string literals only, so a gateway routes on a **string** reduce output — use `first`/`last` (with an
`item_path` selecting a string field). Booleans/numbers feed capabilities, HITL, or further reducers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from amendia_bpmn.dmn import DmnError, _resolve, _test_matches, parse_unary_test
from amendia_bpmn.model import Finding

QUANTIFIERS = ("any", "all", "none")
NUMERIC_OPS = ("sum", "min", "max", "avg")
POSITIONAL = ("first", "last")
OPS = QUANTIFIERS + ("count",) + NUMERIC_OPS + POSITIONAL
# Ops whose semantics are meaningless without a per-item predicate.
PREDICATE_REQUIRED = set(QUANTIFIERS)


class ReduceError(Exception):
    """The reduce config is malformed (e.g. not an object) — a structural/parse issue."""


class ReduceEvaluationError(Exception):
    """A *runtime* failure on a config that passed validation — the source didn't resolve to a list, a
    numeric op hit an empty list / a non-numeric value, or a required predicate was missing. This is a
    **technical** failure (a config that validated but misfires is a bug), so the runtime raises it as a
    ``CapabilityError`` — never routed to an error boundary (same discipline as the decision kind)."""


@dataclass
class ReduceConfig:
    op: str
    source: str = "."               # dotpath to the list (rooted on the binding inputs), or "."/"" = sole input
    item_path: Optional[str] = None  # dotpath into each item selecting the predicate/aggregation value
    predicate: Optional[str] = None  # a single bounded DMN unary test (defines a "matching" item)
    output_field: str = "result"    # the summary artifact field that receives the result


def parse_reduce_config(spec: Dict[str, Any]) -> ReduceConfig:
    """Build a :class:`ReduceConfig` from the normalized JSON on a ``reduce`` capability's runtime."""
    if not isinstance(spec, dict):
        raise ReduceError(f"reduce config must be a JSON object, got {type(spec).__name__}")
    return ReduceConfig(
        op=str(spec.get("op", "")).lower(),
        source=spec.get("source") or ".",
        item_path=spec.get("item_path"),
        predicate=spec.get("predicate"),
        output_field=spec.get("output_field") or "result",
    )


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def _resolve_source(source: str, inputs: Dict[str, Any]) -> Any:
    """Resolve ``source`` (a dotpath rooted on the binding inputs) to a value; ``.``/empty = the sole
    input's value (the common "the input artifact IS the list" case)."""
    if source in ("", ".", None):
        if len(inputs) == 1:
            return next(iter(inputs.values()))
        raise ReduceEvaluationError(
            "reduce source '.' is ambiguous — the binding has %d inputs (name the source)" % len(inputs))
    return _resolve(source, inputs)


def _item_value(item_path: Optional[str], item: Any) -> Any:
    """The per-item value the predicate/aggregation reads — ``item_path`` into the item, or the item
    itself when no ``item_path``."""
    if not item_path or item_path == ".":
        return item
    return _resolve(item_path, item) if isinstance(item, dict) else None


def _num(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ReduceEvaluationError(f"reduce numeric op requires numeric item values, got {v!r}")
    return v


def evaluate_reduce(config: ReduceConfig, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate the reduce over the bound ``inputs`` (``{binding_input_name: data}``) and return the
    summary ``{output_field: value}``. Raises :class:`ReduceEvaluationError` on a runtime failure."""
    lst = _resolve_source(config.source, inputs)
    if not isinstance(lst, list):
        raise ReduceEvaluationError(
            f"reduce source '{config.source}' did not resolve to a list (got {type(lst).__name__})")
    op = config.op
    pred = parse_unary_test(config.predicate) if config.predicate else None
    if op in PREDICATE_REQUIRED and pred is None:
        raise ReduceEvaluationError(f"reduce op '{op}' requires a predicate")

    def matches(it: Any) -> bool:
        return _test_matches(pred, _item_value(config.item_path, it))

    if op == "any":
        val: Any = any(matches(it) for it in lst)
    elif op == "all":
        val = all(matches(it) for it in lst)
    elif op == "none":
        val = not any(matches(it) for it in lst)
    elif op == "count":
        val = sum(1 for it in lst if matches(it)) if pred else len(lst)
    elif op in NUMERIC_OPS:
        nums = [_num(_item_value(config.item_path, it)) for it in lst]
        if op == "sum":
            val = sum(nums) if nums else 0
        elif op == "avg":
            val = (sum(nums) / len(nums)) if nums else 0
        else:  # min / max
            if not nums:
                raise ReduceEvaluationError(f"reduce_numeric_empty: '{op}' over an empty list")
            val = min(nums) if op == "min" else max(nums)
    elif op in POSITIONAL:
        cand = [it for it in lst if matches(it)] if pred else list(lst)
        if not cand:
            val = None
        else:
            it = cand[0] if op == "first" else cand[-1]
            val = _item_value(config.item_path, it)
    else:
        raise ReduceEvaluationError(f"unknown reduce op '{op}'")
    return {config.output_field: val}


# --------------------------------------------------------------------------- #
# Structural validation (registry) — config-only checks
# --------------------------------------------------------------------------- #
def validate_reduce(config: ReduceConfig) -> List[Finding]:
    """Config-only structural validation (ADR-038) — the checks needing no binding/schema context.
    Source/output mapping (``reduce_source_missing`` / ``reduce_output_unmapped``) and the numeric-type
    check live in the registry, which has the binding + schemas."""
    out: List[Finding] = []
    if config.op not in OPS:
        out.append(Finding("reduce_unknown_op",
                           f"unknown reduce op '{config.op}' (allowed: {', '.join(OPS)})", severity="error"))
    if config.predicate is not None:
        try:
            parse_unary_test(config.predicate)
        except DmnError as exc:
            out.append(Finding("reduce_bad_predicate",
                               f"reduce predicate is not a legal unary test: {config.predicate!r} ({exc})",
                               severity="error"))
    if config.op in PREDICATE_REQUIRED and not config.predicate:
        out.append(Finding("reduce_predicate_required",
                           f"reduce op '{config.op}' requires a per-item predicate", severity="error"))
    return out
