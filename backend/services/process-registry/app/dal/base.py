# app/dal/base.py
"""Shared repository helpers."""
from __future__ import annotations

from typing import Any, Dict

from amendia_contracts.common import utcnow


class DuplicateError(Exception):
    """A document with the same natural key already exists (→ HTTP 409)."""

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"{what} already exists")


def utcnow_iso() -> str:
    return utcnow().isoformat()


def stamp_new(doc: Dict[str, Any]) -> Dict[str, Any]:
    now = utcnow_iso()
    if not doc.get("created_at"):
        doc["created_at"] = now
    doc["updated_at"] = now
    return doc
