# app/validation/report.py
"""ValidationReport + Finding models — the output of the pack validator."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from amendia_contracts.common import utcnow


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    code: str
    severity: Severity
    message: str
    stage: int = 0
    element_id: Optional[str] = None
    path: Optional[str] = None
    # Condition-hardening: a machine reason (missing_field | unquoted_rhs | unsupported_operator |
    # wrapper_unresolved | not_parseable) + a structured suggestion the UI renders as a guided fix.
    reason: Optional[str] = None
    suggestion: Optional[Dict[str, Any]] = None


class ValidationReport(BaseModel):
    pack_key: str
    pack_version: str
    findings: List[Finding] = Field(default_factory=list)
    # Condition-hardening: the guided Tier-2 condition findings, surfaced as a first-class list for the UI's
    # Gateways step (each carries reason + a structured suggestion). Populated in finalize().
    condition_issues: List[Finding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    # -- building --
    def add(
        self,
        code: str,
        severity: Severity,
        message: str,
        *,
        stage: int = 0,
        element_id: Optional[str] = None,
        path: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[Dict[str, Any]] = None,
    ) -> Finding:
        f = Finding(
            code=code, severity=severity, message=message,
            stage=stage, element_id=element_id, path=path, reason=reason, suggestion=suggestion,
        )
        self.findings.append(f)
        return f

    def error(self, code: str, message: str, **kw) -> Finding:
        return self.add(code, Severity.ERROR, message, **kw)

    def warning(self, code: str, message: str, **kw) -> Finding:
        return self.add(code, Severity.WARNING, message, **kw)

    def info(self, code: str, message: str, **kw) -> Finding:
        return self.add(code, Severity.INFO, message, **kw)

    # -- queries --
    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def ok(self) -> bool:
        return not self.has_errors

    def error_codes(self) -> List[str]:
        return [f.code for f in self.findings if f.severity is Severity.ERROR]

    def finalize(self) -> "ValidationReport":
        """Deterministic ordering: by stage, then element_id, then code."""
        self.findings.sort(key=lambda f: (f.stage, f.element_id or "", f.code, f.path or ""))
        self.condition_issues = [f for f in self.findings if f.code == "gateway_condition_grammar"]
        return self
