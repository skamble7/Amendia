# app/engine/executor/memo.py
"""Per-instance capability memoization (ADR-019 — fixes ADR-016 trap 2 / ADR-017 trap 5).

LangGraph re-executes an interrupted node from the top on every HITL resume, so an
``llm`` node would call the model **again** on approve — the regenerated (non-deterministic)
artifact, not the one the human reviewed, is what commits. This module memoizes a
capability's produced outputs per instance so a resume replays the node cheaply and commits
the **reviewed** artifact.

Design (host owns the store; the sandbox never writes it — ADR-017 trap 2):

* Keyed on ``(process_instance_id, element_id, inputs_hash, attempt, visit)``. Two counters make replays
  correct under LangGraph's replay-from-top model:
    - **attempt** — the reject → re-run counter, reconstructed identically on every replay, so a genuine
      reject (attempt N+1) is a real miss that re-invokes while a *replay* of an earlier attempt is a hit.
    - **visit** — the loop back-edge counter (ADR-019 §rework loops). A capability re-entered through a loop
      (e.g. ObtainInfo → Assess) is a NEW graph visit and MUST re-execute — else the re-assessment the loop
      exists to perform never happens. The host derives ``visit`` from the committed ``actor_log`` (count of
      this element's prior entries): a HITL **replay** of the same execution has the same count (the node's
      entry commits only on return) → memo hit, side-effect-once preserved; a **loop re-entry** sees the prior
      iteration's committed entry → higher count → memo miss → re-run. See ADR-019 for the full trace.
* ``MongoMemoStore`` persists to a runtime-private collection so the memo survives
  interrupt/resume **and** crash and is auditable. ``InMemoryMemoStore`` is the test/no-Mongo
  double. ``memoized_execute`` is the shared helper both executors call at entry.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Protocol

logger = logging.getLogger(__name__)


def inputs_hash(inputs: Dict[str, Any]) -> str:
    """Stable content hash of the gathered inputs a capability ran on."""
    payload = json.dumps(inputs or {}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class MemoStore(Protocol):
    def get(self, pid: str, element_id: str, inputs_hash: str, attempt: int,
            visit: int = 0) -> Optional[Dict[str, Any]]:
        ...

    def put(self, pid: str, element_id: str, inputs_hash: str, attempt: int,
            outputs: Dict[str, Any], exec_meta: Optional[Dict[str, Any]], visit: int = 0) -> None:
        ...


def _key(pid: str, element_id: str, ih: str, attempt: int, visit: int = 0) -> str:
    # ``visit`` defaults to 0 so a straight-through instance (no loops) keys identically to before.
    return f"{pid}::{element_id}::{ih}::{attempt}::v{visit}"


class InMemoryMemoStore:
    """Process-local memo — the test/no-Mongo double. Not crash-durable."""

    def __init__(self) -> None:
        self._d: Dict[str, Dict[str, Any]] = {}

    def get(self, pid, element_id, inputs_hash, attempt, visit=0):
        return self._d.get(_key(pid, element_id, inputs_hash, attempt, visit))

    def put(self, pid, element_id, inputs_hash, attempt, outputs, exec_meta, visit=0):
        self._d[_key(pid, element_id, inputs_hash, attempt, visit)] = {
            "outputs": outputs, "exec_meta": exec_meta,
        }


class MongoMemoStore:
    """Mongo-backed memo (sync pymongo collection — like the checkpointer). Crash-durable
    and auditable. Upserts are idempotent under redelivery/replay; entries are scoped to a
    single ``process_instance_id`` so one instance never reads another's memo."""

    def __init__(self, collection: Any) -> None:
        self._col = collection

    def get(self, pid, element_id, inputs_hash, attempt, visit=0):
        doc = self._col.find_one({"_id": _key(pid, element_id, inputs_hash, attempt, visit)})
        if not doc:
            return None
        return {"outputs": doc.get("outputs"), "exec_meta": doc.get("exec_meta")}

    def put(self, pid, element_id, inputs_hash, attempt, outputs, exec_meta, visit=0):
        _id = _key(pid, element_id, inputs_hash, attempt, visit)
        self._col.update_one(
            {"_id": _id},
            {"$set": {
                "_id": _id,
                "process_instance_id": pid,
                "element_id": element_id,
                "inputs_hash": inputs_hash,
                "attempt": attempt,
                "visit": visit,
                "outputs": outputs,
                "exec_meta": exec_meta,
                "produced_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )


def build_mongo_memo_store(settings) -> "MongoMemoStore":
    """Construct the Mongo-backed memo over a runtime-private collection (same db as the
    checkpointer). Sync pymongo, mirroring how the checkpointer is built."""
    from pymongo import MongoClient as PyMongoClient

    client = PyMongoClient(settings.MONGO_URI)
    col = client[settings.MONGO_DB][settings.MEMO_COLLECTION]
    return MongoMemoStore(col)


def memoized_execute(
    *,
    memo: Optional[MemoStore],
    enabled: bool,
    inputs: Dict[str, Any],
    ctx: Any,
    run: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    """Wrap a capability execution with memo lookup/upsert.

    Only ``execute``-mode invocations that produce ``outputs`` are memoized — ``propose``
    (approve_actions pre-gate) is never cached. ``ctx.extras`` supplies
    ``process_instance_id`` (the LangGraph thread id), ``element_id``, and ``memo_attempt``.
    On a **hit** the memoized outputs are returned without invoking the capability/model; on
    a **miss** the capability runs and the result is upserted before returning.
    """
    if not enabled or memo is None or getattr(ctx, "mode", "execute") != "execute":
        return run()
    extras = getattr(ctx, "extras", None) or {}
    pid = extras.get("process_instance_id")
    element_id = extras.get("element_id")
    if not pid or not element_id:
        return run()
    ih = inputs_hash(inputs)
    attempt = int(extras.get("memo_attempt", 0) or 0)
    visit = int(extras.get("memo_visit", 0) or 0)   # ADR-019 §rework loops: loop back-edge re-entry counter

    hit = memo.get(pid, element_id, ih, attempt, visit)
    if hit is not None and hit.get("outputs"):
        out: Dict[str, Any] = {"outputs": hit["outputs"],
                               "log": f"memoized artifact reused (attempt {attempt}, visit {visit}) — capability not re-invoked"}
        if hit.get("exec_meta"):
            out["exec_meta"] = hit["exec_meta"]
        logger.info("[%s] memo hit (instance=%s attempt=%d visit=%d) — skipping capability",
                    element_id, pid, attempt, visit)
        return out

    result = run()
    outputs = result.get("outputs") if isinstance(result, dict) else None
    if outputs:
        memo.put(pid, element_id, ih, attempt, outputs, result.get("exec_meta"), visit)
    return result
