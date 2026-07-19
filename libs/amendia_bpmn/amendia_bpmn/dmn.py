# amendia_bpmn/dmn.py
"""Native DMN decision tables — a scoped, auditable evaluator (ADR-037).

Shared by the process-registry (table validation) and the agent-runtime (evaluation) — one
implementation, like the BPMN parser. Deliberately narrow, mirroring the philosophy of ``expr.py``:
a bounded FEEL *unary-test* surface + the common hit policies, and NOTHING else (no FEEL functions,
arithmetic, contexts, or BKMs). A cell outside the surface is a **validation error**, never a silent
pass. Evaluation is pure over ``(table, inputs)`` — no clock, no I/O — so it is fully deterministic;
rule order is table order.

Bounded unary-test surface (per cell):
  - ``-``                 irrelevant / always matches
  - ``"PADDED"`` / ``42`` / ``true``   literal equality (string / number / boolean)
  - ``< <= > >= =`` x     comparison against a literal
  - ``[a..b] (a..b] [a..b) (a..b)``   ranges (inclusive/exclusive bounds)
  - ``"A","B",3``         enumeration (comma-separated literals; matches any)
  - ``not( inner )``      negation of an inner test

Hit policies: ``UNIQUE`` (exactly one match, else error), ``FIRST`` (first in order), ``PRIORITY``
(highest by the first output's ``priority_order``), ``ANY`` (many may match but all must agree),
``COLLECT`` (all matches → a list; no aggregators — deferred).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from xml.etree import ElementTree as ET

from amendia_bpmn.model import Finding, local_name

HIT_POLICIES = ("UNIQUE", "FIRST", "PRIORITY", "ANY", "COLLECT")


class DmnError(Exception):
    """A decision table is malformed or an unresolvable value was hit while parsing a cell."""


class DecisionEvaluationError(Exception):
    """A *runtime* hit-policy violation on a table that passed validation — a UNIQUE/ANY conflict or
    no-match. This is a **technical** failure (a misconfigured table is a bug), NOT a modeled business
    outcome, so the runtime raises it as a ``CapabilityError`` — never routed to an error boundary."""


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
@dataclass
class DecisionInput:
    expression: str                 # dotpath into a bound input artifact, e.g. "dossier.gpi_status.status"
    type: Optional[str] = None      # advisory: "string" | "number" | "boolean"


@dataclass
class DecisionOutput:
    name: str                       # the verdict artifact field this column maps to
    type: Optional[str] = None
    priority_order: Optional[List[Any]] = None   # PRIORITY hit policy: values ranked high → low


@dataclass
class DecisionRule:
    when: List[str]                 # one unary-test cell per input column (table order)
    then: List[Any]                 # one raw output value per output column (table order)
    priority: Optional[int] = None  # optional numeric priority (unused by the spec'd policies)


@dataclass
class DecisionTable:
    hit_policy: str
    inputs: List[DecisionInput] = field(default_factory=list)
    outputs: List[DecisionOutput] = field(default_factory=list)
    rules: List[DecisionRule] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing: normalized JSON  |  DMN XML  →  DecisionTable
# --------------------------------------------------------------------------- #
def parse_decision_table(spec: Union[Dict[str, Any], str]) -> DecisionTable:
    """Build a :class:`DecisionTable` from the normalized JSON stored inline on a ``decision``
    capability's runtime, or from raw DMN XML (a ``<decisionTable>`` — used by authoring). Raises
    :class:`DmnError` on a shape that isn't a table at all; per-cell legality is ``validate_table``."""
    if isinstance(spec, str):
        return _parse_dmn_xml(spec)
    if not isinstance(spec, dict):
        raise DmnError(f"decision table must be a JSON object or DMN XML, got {type(spec).__name__}")
    hit_policy = str(spec.get("hit_policy") or spec.get("hitPolicy") or "UNIQUE").upper()
    inputs = [DecisionInput(expression=str(i.get("expression", "")), type=i.get("type"))
              for i in (spec.get("inputs") or [])]
    outputs = [DecisionOutput(name=str(o.get("name", "")), type=o.get("type"),
                              priority_order=o.get("priority_order"))
               for o in (spec.get("outputs") or [])]
    rules = [DecisionRule(when=list(r.get("when") or []), then=list(r.get("then") or []),
                          priority=r.get("priority"))
             for r in (spec.get("rules") or [])]
    return DecisionTable(hit_policy=hit_policy, inputs=inputs, outputs=outputs, rules=rules)


def _parse_dmn_xml(xml: str) -> DecisionTable:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DmnError(f"DMN XML did not parse: {exc}") from exc
    dt = next((e for e in root.iter() if local_name(e.tag) == "decisionTable"), None)
    if dt is None:
        raise DmnError("no <decisionTable> element found in DMN XML")
    hit_policy = (dt.get("hitPolicy") or "UNIQUE").upper()
    inputs: List[DecisionInput] = []
    outputs: List[DecisionOutput] = []
    for child in dt:
        ln = local_name(child.tag)
        if ln == "input":
            ie = next((c for c in child if local_name(c.tag) == "inputExpression"), None)
            text = None
            if ie is not None:
                t = next((c for c in ie if local_name(c.tag) == "text"), None)
                text = (t.text or "").strip() if t is not None else None
            inputs.append(DecisionInput(expression=text or child.get("label") or "",
                                        type=(ie.get("typeRef") if ie is not None else None)))
        elif ln == "output":
            outputs.append(DecisionOutput(name=child.get("name") or child.get("label") or "",
                                          type=child.get("typeRef")))
    rules: List[DecisionRule] = []
    for child in dt:
        if local_name(child.tag) != "rule":
            continue
        when: List[str] = []
        then: List[Any] = []
        for gc in child:
            lg = local_name(gc.tag)
            if lg == "inputEntry":
                t = next((c for c in gc if local_name(c.tag) == "text"), None)
                when.append((t.text or "").strip() if t is not None else "-")
            elif lg == "outputEntry":
                t = next((c for c in gc if local_name(c.tag) == "text"), None)
                raw = (t.text or "").strip() if t is not None else ""
                then.append(_parse_literal(raw) if raw else None)
        rules.append(DecisionRule(when=when, then=then))
    return DecisionTable(hit_policy=hit_policy, inputs=inputs, outputs=outputs, rules=rules)


# --------------------------------------------------------------------------- #
# Bounded FEEL unary tests
# --------------------------------------------------------------------------- #
# A parsed unary test is a small tagged tuple; see the module docstring for the surface.
_RANGE = re.compile(r"^([\[\(])\s*(.+?)\s*\.\.\s*(.+?)\s*([\]\)])$")
_CMP = re.compile(r"^(<=|>=|<|>|=)\s*(.+)$")


def _parse_literal(tok: str) -> Any:
    """A single FEEL literal: a quoted string, ``true``/``false``, or a number. Anything else (a bare
    unquoted word) is illegal — strings MUST be quoted, so the surface stays unambiguous."""
    t = tok.strip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return t[1:-1]
    if t == "true":
        return True
    if t == "false":
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        raise DmnError(f"illegal literal (quote strings): {tok!r}")


def parse_unary_test(cell: str) -> Tuple:
    """Parse one table cell into a tagged test. Raises :class:`DmnError` if the cell is not one of the
    bounded forms (the caller turns that into a ``dmn_bad_unary_test`` finding)."""
    s = (cell or "").strip()
    if s == "" or s == "-":
        return ("any",)
    if s.startswith("not(") and s.endswith(")"):
        return ("not", parse_unary_test(s[4:-1]))
    m = _RANGE.match(s)
    if m:
        return ("range", m.group(1) == "[", _parse_literal(m.group(2)),
                _parse_literal(m.group(3)), m.group(4) == "]")
    m = _CMP.match(s)
    if m:
        return ("cmp", m.group(1), _parse_literal(m.group(2)))
    if "," in s:
        return ("in", [_parse_literal(p) for p in s.split(",")])
    return ("eq", _parse_literal(s))


def _numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _test_matches(parsed: Tuple, value: Any) -> bool:
    tag = parsed[0]
    if tag == "any":
        return True
    if tag == "eq":
        return value == parsed[1]
    if tag == "in":
        return value in parsed[1]
    if tag == "not":
        return not _test_matches(parsed[1], value)
    if tag == "cmp":
        op, lit = parsed[1], parsed[2]
        if op == "=":
            return value == lit
        if not (_numeric(value) and _numeric(lit)):
            return False
        return {"<": value < lit, "<=": value <= lit, ">": value > lit, ">=": value >= lit}[op]
    if tag == "range":
        _, lo_incl, lo, hi, hi_incl = parsed
        if not (_numeric(value) and _numeric(lo) and _numeric(hi)):
            return False
        lo_ok = value >= lo if lo_incl else value > lo
        hi_ok = value <= hi if hi_incl else value < hi
        return lo_ok and hi_ok
    return False  # pragma: no cover - exhaustive above


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def _resolve(expression: str, inputs: Dict[str, Any]) -> Any:
    """Resolve an input expression dotpath against the bound inputs (``{binding_input_name: data}``)."""
    cur: Any = inputs
    for seg in expression.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _rule_matches(table: DecisionTable, rule: DecisionRule, values: List[Any]) -> bool:
    return all(_test_matches(parse_unary_test(rule.when[i]), values[i]) for i in range(len(table.inputs)))


def _rule_output(table: DecisionTable, rule: DecisionRule) -> Dict[str, Any]:
    return {out.name: rule.then[j] for j, out in enumerate(table.outputs)}


def evaluate(table: DecisionTable, inputs: Dict[str, Any]) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """Evaluate the table over the bound ``inputs`` and return the verdict — a ``{output_field: value}``
    dict for single-hit policies, or a ``list`` of them for ``COLLECT``. Raises
    :class:`DecisionEvaluationError` on a runtime hit-policy violation (UNIQUE ≠1 match, ANY conflict,
    or no match for a single-hit policy)."""
    values = [_resolve(inp.expression, inputs) for inp in table.inputs]
    matches = [r for r in table.rules if _rule_matches(table, r, values)]
    hp = table.hit_policy

    if hp == "COLLECT":
        return [_rule_output(table, r) for r in matches]

    if not matches:
        raise DecisionEvaluationError(f"no rule matched (hit policy {hp}); inputs={values}")

    if hp == "UNIQUE":
        if len(matches) != 1:
            raise DecisionEvaluationError(
                f"UNIQUE hit policy matched {len(matches)} rules (must be exactly one); inputs={values}")
        return _rule_output(table, matches[0])
    if hp == "FIRST":
        return _rule_output(table, matches[0])
    if hp == "ANY":
        outs = [_rule_output(table, r) for r in matches]
        if any(o != outs[0] for o in outs):
            raise DecisionEvaluationError(
                f"ANY hit policy matched {len(matches)} rules with conflicting outputs; inputs={values}")
        return outs[0]
    if hp == "PRIORITY":
        order = table.outputs[0].priority_order or []
        first = table.outputs[0].name

        def rank(r: DecisionRule) -> int:
            v = _rule_output(table, r)[first]
            return order.index(v) if v in order else len(order)

        return _rule_output(table, min(matches, key=rank))
    raise DecisionEvaluationError(f"unknown hit policy '{hp}'")  # pragma: no cover - validated upstream


# --------------------------------------------------------------------------- #
# Structural validation (registry) — table-only checks
# --------------------------------------------------------------------------- #
def validate_table(table: DecisionTable) -> List[Finding]:
    """Structural (table-only) validation — the checks that need no binding/schema context (ADR-037).
    Input/output *mapping* checks (``dmn_input_unresolved`` / ``dmn_output_unmapped``) and the produced-
    upstream rule live in the registry, which has the binding + schema."""
    out: List[Finding] = []

    if table.hit_policy not in HIT_POLICIES:
        out.append(Finding("dmn_unknown_hit_policy",
                           f"unknown DMN hit policy '{table.hit_policy}' (allowed: {', '.join(HIT_POLICIES)})",
                           severity="error"))
    if not table.inputs or not table.outputs or not table.rules:
        out.append(Finding("dmn_table_malformed",
                           f"decision table needs ≥1 input, ≥1 output and ≥1 rule "
                           f"(have inputs={len(table.inputs)} outputs={len(table.outputs)} rules={len(table.rules)})",
                           severity="error"))
    if table.hit_policy == "PRIORITY" and (not table.outputs or not table.outputs[0].priority_order):
        out.append(Finding("dmn_table_malformed",
                           "PRIORITY hit policy requires the first output to declare a 'priority_order'",
                           severity="error"))

    for ri, rule in enumerate(table.rules):
        if len(rule.when) != len(table.inputs):
            out.append(Finding("dmn_table_malformed",
                               f"rule {ri} has {len(rule.when)} input cells but the table has "
                               f"{len(table.inputs)} inputs", severity="error"))
        if len(rule.then) != len(table.outputs):
            out.append(Finding("dmn_table_malformed",
                               f"rule {ri} has {len(rule.then)} output cells but the table has "
                               f"{len(table.outputs)} outputs", severity="error"))
        for ci, cell in enumerate(rule.when):
            try:
                parse_unary_test(cell)
            except DmnError as exc:
                out.append(Finding("dmn_bad_unary_test",
                                   f"rule {ri} input cell {ci} is not a legal unary test: {cell!r} ({exc})",
                                   severity="error"))

    # Static overlap (UNIQUE/ANY): flag two rules we can PROVE share a matching value (best-effort —
    # only confident overlaps, no false positives; the runtime still guards the general case).
    if table.hit_policy in ("UNIQUE", "ANY") and not out:
        n = len(table.rules)
        for a in range(n):
            for b in range(a + 1, n):
                if _rules_definitely_overlap(table.rules[a], table.rules[b], len(table.inputs)):
                    same = _rule_output(table, table.rules[a]) == _rule_output(table, table.rules[b])
                    if table.hit_policy == "UNIQUE" or (table.hit_policy == "ANY" and not same):
                        out.append(Finding(
                            "dmn_rules_overlap",
                            f"rules {a} and {b} statically overlap under hit policy {table.hit_policy} "
                            f"(both can match the same inputs)", severity="error"))
    return out


def _cells_compatible(a: str, b: str) -> bool:
    """True only when we can PROVE the two cells share a matching value (else False — never a false
    positive). Handles dash, equal literals, enum intersection, and numeric ranges/comparisons."""
    try:
        pa, pb = parse_unary_test(a), parse_unary_test(b)
    except DmnError:
        return False
    if pa[0] == "any" or pb[0] == "any":
        return True
    lits_a = _literal_set(pa)
    lits_b = _literal_set(pb)
    if lits_a is not None and lits_b is not None:
        return bool(lits_a & lits_b)
    # literal(s) vs a numeric predicate → a shared value iff some literal satisfies the predicate.
    if lits_a is not None and _is_numeric_pred(pb):
        return any(_test_matches(pb, v) for v in lits_a)
    if lits_b is not None and _is_numeric_pred(pa):
        return any(_test_matches(pa, v) for v in lits_b)
    if _is_numeric_pred(pa) and _is_numeric_pred(pb):
        return _numeric_preds_overlap(pa, pb)
    return False


def _literal_set(parsed: Tuple):
    if parsed[0] == "eq":
        return {parsed[1]}
    if parsed[0] == "in":
        return set(parsed[1])
    return None


def _is_numeric_pred(parsed: Tuple) -> bool:
    return parsed[0] == "range" or (parsed[0] == "cmp" and parsed[1] != "=")


def _numeric_preds_overlap(pa: Tuple, pb: Tuple) -> bool:
    la, ha = _pred_interval(pa)
    lb, hb = _pred_interval(pb)
    lo = max(la, lb)
    hi = min(ha, hb)
    return lo <= hi


def _pred_interval(parsed: Tuple) -> Tuple[float, float]:
    inf = float("inf")
    if parsed[0] == "range":
        _, _, lo, hi, _ = parsed
        return float(lo), float(hi)
    op, lit = parsed[1], float(parsed[2])
    if op in ("<", "<="):
        return -inf, lit
    if op in (">", ">="):
        return lit, inf
    return lit, lit


def _rules_definitely_overlap(a: DecisionRule, b: DecisionRule, n_inputs: int) -> bool:
    return all(_cells_compatible(a.when[i], b.when[i]) for i in range(n_inputs))
