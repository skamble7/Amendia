# app/validation/bpmn.py
"""BPMN Stage-1 adapter over the shared ``amendia_bpmn`` parser.

The parse/subset logic lives in the shared ``amendia_bpmn`` package (so the
agent-runtime graph compiler reuses the exact same element subset and topology).
This module keeps the registry-facing API stable — ``parse_and_validate`` still
takes a ``ValidationReport``, adds the manifest-coupled sha256 check, and maps the
shared parser's neutral findings 1:1 into the report as Stage-1 errors.
"""
from __future__ import annotations

from typing import Optional

from amendia_bpmn import BpmnModel, Flow, compute_sha256, parse  # noqa: F401 (re-exported)

from app.validation.report import ValidationReport

STAGE = 1

__all__ = ["BpmnModel", "Flow", "compute_sha256", "parse_and_validate", "STAGE"]


def parse_and_validate(
    xml: str,
    *,
    expected_process_id: str,
    expected_sha256: Optional[str],
    report: ValidationReport,
) -> Optional[BpmnModel]:
    """Run Stage-1 checks; append findings; return a BpmnModel or None on hard failure."""
    # sha256 match (manifest-coupled — stays in the registry)
    if expected_sha256 is not None:
        actual = compute_sha256(xml)
        if actual != expected_sha256:
            report.error("bpmn_sha_mismatch", stage=STAGE,
                         message=f"manifest bpmn_sha256 {expected_sha256} != actual {actual}")

    model, findings = parse(xml, expected_process_id)
    for f in findings:
        report.error(f.code, stage=STAGE, element_id=f.element_id, message=f.message)
    return model
