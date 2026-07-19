# app/validation/reduce.py
"""Registry validation rules for the `reduce` capability kind — collection reduction (ADR-038).

A `reduce` capability collapses a list input artifact into a scalar/summary output. These checks refuse
a malformed config at activation off the SAME shared evaluator (`amendia_bpmn.reduce`) the runtime runs
with, so registry and runtime never diverge. All additive — a pack with no reduce binding is untouched.
"""
from __future__ import annotations

from typing import Dict, Optional

from amendia_bpmn import BpmnModel, parse_reduce_config, validate_reduce
from amendia_bpmn.reduce import NUMERIC_OPS
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.validation.report import ValidationReport


def _kind(desc: CapabilityDescriptor) -> str:
    return desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)


def _declared_item_type(input_schemas: Dict[str, dict], b_inputs, config) -> Optional[str]:
    """Best-effort: the JSON-Schema ``type`` an item's ``item_path`` value is declared as — used for the
    numeric-type check. Handles the common case where a binding input's schema IS the list-item schema
    (as multi-instance list aggregation produces); returns ``None`` (skip) for anything less certain, so
    there are no false positives."""
    src = (config.source or ".").strip()
    if src in ("", "."):
        if len(b_inputs) != 1:
            return None
        ref = b_inputs[0].schema_.ref_id
    else:
        segs = src.split(".")
        if len(segs) != 1:
            return None  # nested list — can't cheaply locate the item schema
        io = next((io for io in b_inputs if io.name == segs[0]), None)
        if io is None:
            return None
        ref = io.schema_.ref_id
    node = input_schemas.get(ref)
    if not isinstance(node, dict):
        return None
    if config.item_path and config.item_path != ".":
        for seg in config.item_path.split("."):
            props = node.get("properties", {}) if isinstance(node, dict) else {}
            if seg not in props:
                return None
            node = props[seg]
    return node.get("type") if isinstance(node, dict) else None


def validate_reduce_bindings(
    manifest: ProcessPackManifest,
    model: BpmnModel,
    resolved: Dict[str, CapabilityDescriptor],
    input_schemas: Dict[str, dict],
    output_schemas: Dict[str, dict],
    report: ValidationReport,
) -> None:
    """Validate every binding that resolves to a ``reduce`` capability (ADR-038):

    * **config structure** — `reduce_unknown_op`, `reduce_bad_predicate`, `reduce_predicate_required`
      (from the shared ``validate_reduce``);
    * **source mapping** — `reduce_source_missing`: the `source` dotpath root is not a declared binding
      input (or `"."` used with ≠1 inputs);
    * **output mapping** — `reduce_output_unmapped`: `output_field` absent from the summary output schema;
    * **numeric type** — `reduce_numeric_type`: a numeric op whose `item_path` is declared non-numeric
      (best-effort, no false positives)."""
    for b in manifest.bindings:
        ex = b.executor
        if ex.type != "capability":
            continue
        desc = resolved.get(ex.capability.ref_id)
        if desc is None or _kind(desc) != "reduce":
            continue
        el = b.element_id
        config = parse_reduce_config(getattr(desc.runtime, "config", {}) or {})

        for f in validate_reduce(config):
            report.error(f.code, stage=5, element_id=el,
                         message=f"reduce '{desc.capability_id}': {f.message}")

        # source mapping.
        input_names = {io.name for io in b.inputs}
        if config.source in ("", ".", None):
            if len(b.inputs) != 1:
                report.error("reduce_source_missing", stage=5, element_id=el,
                             message=f"reduce source '.' (the whole input) requires exactly one binding "
                                     f"input, but the binding has {len(b.inputs)}")
        elif config.source.split(".")[0] not in input_names:
            report.error("reduce_source_missing", stage=5, element_id=el,
                         message=f"reduce source '{config.source}' roots on "
                                 f"'{config.source.split('.')[0]}', which is not a declared binding input "
                                 f"(declared: {sorted(input_names)})")

        # output mapping.
        out_schema = output_schemas.get(b.outputs[0].schema_.ref_id) if b.outputs else None
        props = out_schema.get("properties", {}) if isinstance(out_schema, dict) else {}
        if props and config.output_field not in props:
            report.error("reduce_output_unmapped", stage=5, element_id=el,
                         message=f"reduce output_field '{config.output_field}' is not a field of the "
                                 f"summary artifact schema (fields: {sorted(props)})")

        # numeric-type (best-effort).
        if config.op in NUMERIC_OPS:
            t = _declared_item_type(input_schemas, b.inputs, config)
            if t in ("string", "boolean"):
                report.error("reduce_numeric_type", stage=5, element_id=el,
                             message=f"reduce numeric op '{config.op}' reads item_path "
                                     f"'{config.item_path}', declared type '{t}' (not numeric)")
