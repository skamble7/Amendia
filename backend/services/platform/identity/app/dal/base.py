# app/dal/base.py
"""Shared repository helpers."""
from __future__ import annotations

from datetime import datetime, timezone


class DuplicateError(Exception):
    """A document with the same natural key already exists (→ HTTP 409)."""

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"{what} already exists")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
