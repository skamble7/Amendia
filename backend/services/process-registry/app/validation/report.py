# app/validation/report.py
"""ValidationReport + Finding models — the output of the pack validator."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

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


class ValidationReport(BaseModel):
    pack_key: str
    pack_version: str
    findings: List[Finding] = Field(default_factory=list)
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
    ) -> Finding:
        f = Finding(
            code=code, severity=severity, message=message,
            stage=stage, element_id=element_id, path=path,
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
        return self
