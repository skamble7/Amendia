# app/clickhouse/sealing.py
"""Per-correlation append-only hash-chain (ADR-058 tamper-evidence). Pure — no I/O — so the chain math
is unit-tested without ClickHouse.

For a correlation's rows in ``(occurred_at, event_id)`` order:
  ``canonical[i] = stable JSON of the IMMUTABLE audit fields`` (INSERT_COLUMNS — excludes
  ``ingested_at``/``prev_hash``/``seal``), ``seal[i] = sha256(canonical[i] || "|" || prev_hash[i])``,
  ``prev_hash[i] = seal[i-1]``, genesis ``prev_hash = ""``.

Tampering with any immutable field (or reordering) changes a canonical row → its seal (and every seal
after it) no longer matches the stored chain → detected by ``verify``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.clickhouse.schema import INSERT_COLUMNS


def _norm(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def canonical_row(row: Dict[str, Any]) -> str:
    """A stable, field-ordered serialization of the immutable audit fields (excludes
    ingested_at/prev_hash/seal). Deterministic: sorted keys, compact separators."""
    payload = {col: _norm(row.get(col)) for col in INSERT_COLUMNS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _seal(canonical: str, prev_hash: str) -> str:
    return hashlib.sha256(f"{canonical}|{prev_hash}".encode("utf-8")).hexdigest()


def _ordered(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (str(r.get("occurred_at")), str(r.get("event_id"))))


def chain(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Compute the chain for a correlation's rows. Returns one ``{event_id, prev_hash, seal}`` per row,
    in chain order. Genesis ``prev_hash = ""``. Deterministic — recomputing the same rows is identical
    (so re-sealing an unchanged correlation is a no-op)."""
    out: List[Dict[str, str]] = []
    prev = ""
    for row in _ordered(rows):
        seal = _seal(canonical_row(row), prev)
        out.append({"event_id": str(row.get("event_id")), "prev_hash": prev, "seal": seal})
        prev = seal
    return out


def verify(rows: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Recompute the chain and compare to the stored ``prev_hash``/``seal`` on each row. Returns
    ``(intact, broken_event_id)`` — ``(True, None)`` when every row matches, else the first event_id
    whose stored chain doesn't match the recomputation (a tampered immutable field, or a broken link)."""
    ordered = _ordered(rows)
    computed = chain(ordered)
    for row, exp in zip(ordered, computed):
        if str(row.get("seal") or "") != exp["seal"] or str(row.get("prev_hash") or "") != exp["prev_hash"]:
            return False, exp["event_id"]
    return True, None
