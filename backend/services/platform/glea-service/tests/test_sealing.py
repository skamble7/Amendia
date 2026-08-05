# tests/test_sealing.py
"""ADR-058 hash-chain sealing — the pure chain/verify math + the sealer orchestration (over a fake
ReplacingMergeTree store, no ClickHouse)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clickhouse import sealing
from app.clickhouse.schema import INSERT_COLUMNS
from app.clickhouse.sealer import AuditSealer


def _row(cid: str, eid: str, occurred_at: datetime, **extra):
    row = {c: "" for c in INSERT_COLUMNS}
    row.update({
        "event_id": eid, "correlation_id": cid, "occurred_at": occurred_at,
        "kind": "artifact_committed", "prev_hash": None, "seal": None,
    })
    row.update(extra)
    return row


# --------------------------------------------------------------------------- #
# pure chain / verify
# --------------------------------------------------------------------------- #
def test_chain_genesis_and_linkage():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    rows = [_row("c", "e1", t0), _row("c", "e2", t0 + timedelta(seconds=1)),
            _row("c", "e3", t0 + timedelta(seconds=2))]
    ch = sealing.chain(rows)
    assert ch[0]["prev_hash"] == ""                 # genesis
    assert ch[1]["prev_hash"] == ch[0]["seal"]      # each prev_hash = the previous seal
    assert ch[2]["prev_hash"] == ch[1]["seal"]
    assert len({c["seal"] for c in ch}) == 3        # distinct seals


def test_chain_is_deterministic_and_order_independent_of_input():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    a = [_row("c", "e1", t0), _row("c", "e2", t0 + timedelta(seconds=1))]
    b = list(reversed(a))                            # same rows, shuffled input
    assert sealing.chain(a) == sealing.chain(b)      # ordered by (occurred_at, event_id) internally


def test_verify_intact_then_broken_on_mutation():
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    rows = [_row("c", "e1", t0, decision="approve"), _row("c", "e2", t0 + timedelta(seconds=1))]
    for row, c in zip(sorted(rows, key=lambda r: r["event_id"]), sealing.chain(rows)):
        row["prev_hash"], row["seal"] = c["prev_hash"], c["seal"]
    assert sealing.verify(rows) == (True, None)
    rows[0]["decision"] = "reject"                   # tamper an immutable field of a sealed row
    intact, broken = sealing.verify(rows)
    assert intact is False and broken == "e1"


# --------------------------------------------------------------------------- #
# sealer orchestration (fake ReplacingMergeTree store)
# --------------------------------------------------------------------------- #
class FakeStore:
    def __init__(self):
        self.rows: dict = {}  # event_id -> row (ReplacingMergeTree keeps one per event_id)

    def add(self, row):
        self.rows[row["event_id"]] = dict(row)


class FakeReader:
    def __init__(self, store):
        self._s = store

    async def sealing_rows(self, cid):
        rows = [dict(r) for r in self._s.rows.values() if r.get("correlation_id") == cid]
        return sorted(rows, key=lambda r: (str(r["occurred_at"]), str(r["event_id"])))

    async def unsealed_quiescent_correlations(self, quiescent_seconds):
        return sorted({r["correlation_id"] for r in self._s.rows.values() if not (r.get("seal") or "")})


class FakeWriter:
    def __init__(self, store):
        self._s = store

    async def reinsert_sealed(self, rows):
        for r in rows:
            self._s.rows[r["event_id"]] = dict(r)  # same event_id → the sealed row wins (FINAL)


def _sealer():
    store = FakeStore()
    return store, AuditSealer(FakeReader(store), FakeWriter(store))


async def test_seal_correlation_populates_and_verifies():
    store, sealer = _sealer()
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    for i in range(3):
        store.add(_row("EXC-1", f"e{i}", t0 + timedelta(seconds=i)))
    n = await sealer.seal_correlation("EXC-1")
    assert n == 3
    sealed = [store.rows[f"e{i}"] for i in range(3)]
    assert all(r["seal"] for r in sealed)
    assert sealed[0]["prev_hash"] == ""              # genesis persisted
    report = await sealer.verify_correlation("EXC-1")
    assert report["intact"] is True and report["sealed"] == 3 and report["broken_event_id"] is None


async def test_sealer_is_idempotent():
    store, sealer = _sealer()
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    store.add(_row("EXC-2", "a", t0))
    store.add(_row("EXC-2", "b", t0 + timedelta(seconds=1)))
    await sealer.seal_correlation("EXC-2")
    seals1 = {k: store.rows[k]["seal"] for k in ("a", "b")}
    await sealer.seal_correlation("EXC-2")           # re-seal identical rows
    seals2 = {k: store.rows[k]["seal"] for k in ("a", "b")}
    assert seals1 == seals2                           # unchanged (deterministic)
    # and no correlations remain unsealed for a quiescent pass
    assert await sealer.seal_quiescent(0) == 0


async def test_seal_quiescent_seals_all_unsealed():
    store, sealer = _sealer()
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    store.add(_row("EXC-A", "a1", t0))
    store.add(_row("EXC-B", "b1", t0))
    assert await sealer.seal_quiescent(0) == 2        # both correlations sealed
    assert await sealer.seal_quiescent(0) == 0        # nothing unsealed left (idempotent)


async def test_verify_detects_a_mutated_sealed_row_via_sealer():
    store, sealer = _sealer()
    t0 = datetime(2026, 8, 4, tzinfo=timezone.utc)
    store.add(_row("EXC-3", "x", t0, actor="cap.a"))
    store.add(_row("EXC-3", "y", t0 + timedelta(seconds=1)))
    await sealer.seal_correlation("EXC-3")
    store.rows["x"]["actor"] = "cap.tampered"          # mutate a sealed immutable field
    report = await sealer.verify_correlation("EXC-3")
    assert report["intact"] is False and report["broken_event_id"] == "x"


async def test_unsealed_correlation_reports_intact_not_broken():
    store, sealer = _sealer()
    store.add(_row("EXC-4", "z", datetime(2026, 8, 4, tzinfo=timezone.utc)))
    report = await sealer.verify_correlation("EXC-4")
    assert report["sealed"] == 0 and report["intact"] is True   # unsealed ≠ broken
