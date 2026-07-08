# app/dal/base.py
"""Shared repository helpers: duplicate-key error, timestamp stamping, semver picks."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, TypeVar

from packaging.version import InvalidVersion, Version

from app.models.common import ContractModel, utcnow


class DuplicateError(Exception):
    """A document with the same natural key already exists (→ HTTP 409)."""

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"{what} already exists")


def stamp_new(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Set store-managed created_at/updated_at (ISO strings) on a fresh document."""
    now = utcnow().isoformat()
    doc.setdefault("created_at", None)
    if not doc.get("created_at"):
        doc["created_at"] = now
    doc["updated_at"] = now
    return doc


T = TypeVar("T", bound=ContractModel)


def latest_active(models: Iterable[T], *, version_attr: str = "version",
                  status_attr: str = "status", active_value: str = "active") -> Optional[T]:
    """Pick the highest-semver model whose status == active_value."""
    best: Optional[T] = None
    best_v: Optional[Version] = None
    for m in models:
        status = getattr(m, status_attr, None)
        status_val = getattr(status, "value", status)
        if status_val != active_value:
            continue
        try:
            v = Version(getattr(m, version_attr))
        except InvalidVersion:  # pragma: no cover - patterns prevent this
            continue
        if best_v is None or v > best_v:
            best, best_v = m, v
    return best


def sort_by_semver_desc(models: List[T], *, version_attr: str = "version") -> List[T]:
    return sorted(models, key=lambda m: Version(getattr(m, version_attr)), reverse=True)
