# app/engine/state.py
"""The process execution state (LangGraph channels) + reducers.

Everything here is JSON-serializable so the Mongo checkpointer can persist it at
every node boundary — that checkpoint trail is the audit record.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def merge_dicts(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Reducer for ``artifacts``: later node deltas overlay earlier ones."""
    out = dict(a or {})
    out.update(b or {})
    return out


class ProcessState(TypedDict, total=False):
    envelope: Dict[str, Any]
    artifacts: Annotated[Dict[str, Any], merge_dicts]
    actor_log: Annotated[List[Dict[str, Any]], operator.add]
    trace: Dict[str, Any]
    pack: Dict[str, Any]
    outcome: Optional[str]
    last_error: Optional[str]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def actor_entry(element_id: str, actor: str, kind: str,
                meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One ``actor_log`` entry — kind is ``capability`` or ``human``.

    ``meta`` is optional executor metadata (e.g. an OpenShell OTLP ``exec_meta`` in
    nemoclaw mode). It is omitted entirely when absent, so native-mode entries are
    byte-for-byte unchanged (ADR-017 §8.1).
    """
    entry: Dict[str, Any] = {"element_id": element_id, "actor": actor, "kind": kind, "at": now_iso()}
    if meta:
        entry["exec_meta"] = meta
    return entry


def initial_state(*, envelope: Dict[str, Any], trace: Dict[str, Any], pack: Dict[str, Any]) -> ProcessState:
    return {
        "envelope": envelope,
        "artifacts": {},
        "actor_log": [],
        "trace": trace,
        "pack": pack,
        "outcome": None,
        "last_error": None,
    }
