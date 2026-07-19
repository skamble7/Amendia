# app/validation/decision.py
"""Registry validation rules for the ``decision`` capability kind — native DMN (ADR-037).

A `businessRuleTask` may bind a `kind: decision` capability whose runtime carries an inline decision
table. These checks refuse a malformed/unsound table at activation off the SAME shared evaluator
(`amendia_bpmn.dmn`) the runtime evaluates with, so registry and runtime never diverge. All additive:
a `businessRuleTask` bound to a plain (non-decision) capability keeps today's behaviour — native DMN
is opt-in.
"""
from __future__ import annotations

from typing import Dict, Optional

from amendia_bpmn import BpmnModel, parse_decision_table, validate_table
from amendia_bpmn.dmn import DmnError
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.process_pack import ProcessPackManifest
from app.validation.report import ValidationReport


def _kind(desc: CapabilityDescriptor) -> str:
    return desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)


def validate_decision_bindings(
    manifest: ProcessPackManifest,
    model: BpmnModel,
    resolved: Dict[str, CapabilityDescriptor],
    output_schemas: Dict[str, dict],
    report: ValidationReport,
) -> None:
    """Validate every binding that resolves to a ``decision`` capability (ADR-037):

    * **table structure** — `dmn_table_malformed`, `dmn_unknown_hit_policy`, `dmn_bad_unary_test`,
      `dmn_rules_overlap` (from the shared ``validate_table``);
    * **input mapping** — each table input-expression dotpath must root on a **declared binding input**
      (`dmn_input_unresolved`; produced-upstream itself is enforced by the stage-5 IO checks, mirroring
      the gateway-variable rule);
    * **output mapping** — each output column must be a field of the pinned verdict artifact schema
      (`dmn_output_unmapped`);
    * **decisionRef alignment** — an advisory `businessRuleTask` `decisionRef` that names a *different*
      table id is a `decision_ref_mismatch` warning (it is inference-only, ADR-033).

    ``output_schemas`` maps a decision binding's output artifact key → its pinned json_schema (fetched
    by the caller, which has the schema repo)."""
    for b in manifest.bindings:
        ex = b.executor
        if ex.type != "capability":
            continue
        desc = resolved.get(ex.capability.ref_id)
        if desc is None or _kind(desc) != "decision":
            continue
        el = b.element_id

        # Table structure (shared evaluator).
        try:
            table = parse_decision_table(getattr(desc.runtime, "table", None))
        except DmnError as exc:
            report.error("dmn_table_malformed", stage=5, element_id=el,
                         message=f"decision '{desc.capability_id}' table is malformed: {exc}")
            continue
        for f in validate_table(table):
            report.error(f.code, stage=5, element_id=el,
                         message=f"decision '{desc.capability_id}': {f.message}")

        # Input mapping: each input-expression root must be a declared binding input name.
        input_names = {io.name for io in b.inputs}
        for inp in table.inputs:
            root = (inp.expression or "").split(".")[0]
            if root not in input_names:
                report.error("dmn_input_unresolved", stage=5, element_id=el,
                             message=f"decision input expression '{inp.expression}' roots on '{root}', "
                                     f"which is not a declared input of the binding "
                                     f"(declared: {sorted(input_names)})")

        # Output mapping: each output column must be a field of the verdict artifact schema.
        out_schema: Optional[dict] = None
        if b.outputs:
            out_schema = output_schemas.get(b.outputs[0].schema_.ref_id)
        props = out_schema.get("properties", {}) if isinstance(out_schema, dict) else {}
        if props:
            for out in table.outputs:
                if out.name not in props:
                    report.error("dmn_output_unmapped", stage=5, element_id=el,
                                 message=f"decision output column '{out.name}' is not a field of the "
                                         f"verdict artifact schema (fields: {sorted(props)})")

        # decisionRef alignment (advisory / warning): a diagram decisionRef that names a different table id.
        decision_ref = model.decision_refs.get(el)
        table_id = (getattr(desc.runtime, "table", {}) or {}).get("id")
        if decision_ref and table_id and decision_ref != table_id and decision_ref != desc.capability_id:
            report.warning("decision_ref_mismatch", stage=5, element_id=el,
                           message=f"businessRuleTask decisionRef '{decision_ref}' does not match the bound "
                                   f"decision table id '{table_id}' (advisory — decisionRef is inference-only)")
