# app/clickhouse/sealer.py
"""The sealing pass (ADR-058 tamper-evidence). Orchestrates: find quiescent correlations with unsealed
rows → compute the per-correlation hash-chain (``sealing`` — pure) → persist by re-inserting the rows
with ``prev_hash``/``seal`` set. Idempotent: a fully-sealed correlation has no unsealed rows, so it is
skipped; re-sealing identical rows recomputes an identical chain.

Reads are never blocked — the sealer borrows its own pool clients like any other operation, and the
re-insert is an append that ReplacingMergeTree collapses to the sealed version on ``FINAL`` reads.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.clickhouse import sealing

logger = logging.getLogger(__name__)


class AuditSealer:
    def __init__(self, reader, writer) -> None:
        self._reader = reader
        self._writer = writer

    async def seal_correlation(self, correlation_id: str) -> int:
        """Seal one correlation: compute its chain and re-insert the sealed rows. Returns the number of
        rows sealed (0 if it had none / was already sealed)."""
        rows = await self._reader.sealing_rows(correlation_id)
        if not rows:
            return 0
        computed = {c["event_id"]: c for c in sealing.chain(rows)}
        sealed_rows: List[Dict[str, Any]] = []
        for row in rows:
            c = computed.get(str(row.get("event_id")))
            if c is None:
                continue
            sealed_rows.append({**row, "prev_hash": c["prev_hash"], "seal": c["seal"]})
        await self._writer.reinsert_sealed(sealed_rows)
        return len(sealed_rows)

    async def seal_quiescent(self, quiescent_seconds: int) -> int:
        """Seal every correlation with unsealed rows that has been quiescent for ``quiescent_seconds``.
        Returns the count of correlations sealed this pass."""
        cids = await self._reader.unsealed_quiescent_correlations(quiescent_seconds)
        sealed = 0
        for cid in cids:
            try:
                if await self.seal_correlation(cid) > 0:
                    sealed += 1
            except Exception as exc:  # noqa: BLE001 — one bad correlation must not stall the pass
                logger.warning("sealing correlation %s failed: %s", cid, exc)
        if sealed:
            logger.info("sealed %d correlation(s)", sealed)
        return sealed

    async def verify_correlation(self, correlation_id: str) -> Dict[str, Any]:
        """Recompute the chain for a correlation and report intact/broken (for the verification API)."""
        rows = await self._reader.sealing_rows(correlation_id)
        sealed_count = sum(1 for r in rows if (r.get("seal") or ""))
        if not rows:
            return {"correlation_id": correlation_id, "rows": 0, "sealed": 0, "intact": True, "broken_event_id": None}
        intact, broken = sealing.verify(rows)
        # A correlation with no sealed rows yet isn't "broken" — it's simply unsealed.
        if sealed_count == 0:
            intact, broken = True, None
        return {
            "correlation_id": correlation_id,
            "rows": len(rows),
            "sealed": sealed_count,
            "intact": bool(intact),
            "broken_event_id": broken,
        }
