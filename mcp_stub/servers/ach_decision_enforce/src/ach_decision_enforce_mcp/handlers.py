# handlers.py
"""Deterministic (dumb) tool handlers for the ACH-exposure **Enforce** segment + the tool registry + the
compliance self-check. Carried over verbatim from the combined ach_exposure server (ADR-063 split); only this
segment's tools plus the shared ``notify_pega`` handback are present.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
from typing import Any, Callable, Dict, List

from . import schemas as S

logger = logging.getLogger(__name__)

_FIXED_TS = "2025-01-01T00:00:00Z"
ACTION_TOOLS = {"prepare_release", "request_purge", "notify_pega"}


# --------------------------------------------------------------------------- #
# Permissive input digging (top-level OR one level down inside any payload object)
# --------------------------------------------------------------------------- #

def _dig(args: Dict[str, Any], key: str, default: Any = None) -> Any:
    if key in args and args[key] is not None:
        return args[key]
    for v in args.values():
        if isinstance(v, dict) and v.get(key) is not None:
            return v[key]
    return default


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _case_id(args: Dict[str, Any]) -> str:
    return str(_dig(args, "case_id", "unknown-case"))


def _company(args: Dict[str, Any]) -> str:
    return str(_dig(args, "company", None) or _dig(args, "company_number", None) or "ACME-CORP")


def _hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:16]


def action_id(tool: str, case: str) -> str:
    """Deterministic, idempotent, auditable — a hash of the case id + tool name."""
    return "act-" + _hash(tool, case)


# --------------------------------------------------------------------------- #
# Segment B — Enforce & Execute
# --------------------------------------------------------------------------- #

def capture_decision(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    decision = str(_dig(args, "rbo_decision", "") or "").lower()
    if decision not in ("approve", "reject"):
        decision = "reject"  # safe default (matches the BPMN gateway default)
    underwriter = str(_dig(args, "underwriter", "rbo.underwriter@flagstar.com") or "rbo.underwriter@flagstar.com")
    return {"case_id": case, "rbo_decision": decision, "captured_by": "ach-ops-agent",
            "underwriter": underwriter, "sod_satisfied": True, "decision_id": "dec-" + _hash("decision", case)}


def prepare_release(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    records = _dig(args, "records", [])
    n = len(records) if isinstance(records, list) else 1
    return {"acknowledged": True, "action_id": action_id("prepare_release", case), "status": "performed",
            "performed_at": _FIXED_TS, "case_id": case, "instruction": "release", "marked_items": max(n, 1),
            "release_ref": "REL-" + _hash("release", case)}


def request_purge(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    return {"acknowledged": True, "action_id": action_id("request_purge", case), "status": "performed",
            "performed_at": _FIXED_TS, "case_id": case, "instruction": "purge",
            "tma_ref": "TMA-" + _hash("tma", case), "fis_ticket": "FIS-" + _hash("fis", case)}


# --------------------------------------------------------------------------- #
# Shared — handback to the mock Pega orchestrator (the one tool with a side effect)
# --------------------------------------------------------------------------- #

def notify_pega(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    event = str(_dig(args, "event", "SegmentCompleted") or "SegmentCompleted")
    segment = str(_dig(args, "segment", "") or "")
    result = _dig(args, "result", {})
    target = os.environ.get("PEGA_STUB_URL", "").rstrip("/")
    delivered = False
    if target:
        url = f"{target}/amendia/handback"
        body = json.dumps({"case_id": case, "segment": segment, "event": event, "result": result}).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 (trusted local stub URL)
                delivered = 200 <= resp.status < 300
        except Exception as exc:  # noqa: BLE001 — fail-soft: never break a run on a handback hiccup
            logger.warning("notify_pega: handback to %s failed (case %s): %s", url, case, exc)
    else:
        logger.info("notify_pega: PEGA_STUB_URL unset — handback for case %s not delivered (dry run)", case)
    status = "performed" if delivered else ("queued" if not target else "rejected")
    return {"acknowledged": delivered, "action_id": action_id("notify_pega", case), "status": status,
            "performed_at": _FIXED_TS, "case_id": case, "event": event, "delivered": delivered,
            "target": target or "(unset)"}


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #

def _tool(name: str, desc: str, inp: Dict[str, Any], out: Dict[str, Any],
          handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    return {"name": name, "description": desc, "input_schema": inp, "output_schema": out, "handler": handler}


TOOLS: List[Dict[str, Any]] = [
    _tool("capture_decision", "Capture the RBO underwriter's labelled decision (approve/reject) under separation-of-duties.",
          S.CAPTURE_DECISION_INPUT, S.CAPTURE_DECISION_OUTPUT, capture_decision),
    _tool("prepare_release", "Prepare the release instruction (mark the held items for release to FIS).",
          S.PREPARE_RELEASE_INPUT, S.PREPARE_RELEASE_OUTPUT, prepare_release),
    _tool("request_purge", "Request a purge for a rejected transaction (raise the TMA purge form + FIS ticket).",
          S.REQUEST_PURGE_INPUT, S.REQUEST_PURGE_OUTPUT, request_purge),
    # Shared handback
    _tool("notify_pega", "Hand the segment's result back to the Pega orchestrator (POST to PEGA_STUB_URL).",
          S.NOTIFY_PEGA_INPUT, S.NOTIFY_PEGA_OUTPUT, notify_pega),
]

TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}


# --------------------------------------------------------------------------- #
# Compliance self-check (mirrors the wire stub — refuse to build a bad server)
# --------------------------------------------------------------------------- #

def _assert_closed_output(schema: Dict[str, Any], where: str) -> None:
    if schema.get("type") == "object":
        if schema.get("additionalProperties", None) is not False:
            raise ValueError(f"output schema not closed (additionalProperties!=false): {where}")
        for k, v in (schema.get("properties") or {}).items():
            if isinstance(v, dict):
                _assert_closed_output(v, f"{where}.{k}")
    if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        _assert_closed_output(schema["items"], f"{where}[]")


def _assert_no_ref(schema: Any, where: str) -> None:
    if isinstance(schema, dict):
        if "$ref" in schema:
            raise ValueError(f"external $ref not allowed: {where}")
        for k, v in schema.items():
            _assert_no_ref(v, f"{where}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            _assert_no_ref(v, f"{where}[{i}]")


def check_compliance() -> None:
    """Fail fast at server build time if any tool schema violates the Amendia MCP guideline."""
    names = set()
    for t in TOOLS:
        name = t["name"]
        if name in names:
            raise ValueError(f"duplicate tool name: {name}")
        names.add(name)
        inp, out = t["input_schema"], t["output_schema"]
        if inp.get("type") != "object" or inp.get("additionalProperties", None) is not False:
            raise ValueError(f"input root must be a closed object: {name}")
        if out.get("type") != "object":
            raise ValueError(f"output root must be an object: {name}")
        _assert_closed_output(out, f"{name}.output")
        _assert_no_ref(inp, f"{name}.input")
        _assert_no_ref(out, f"{name}.output")
        if not callable(t["handler"]):
            raise ValueError(f"handler not callable: {name}")
