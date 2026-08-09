# handlers.py
"""Deterministic (dumb) tool handlers for the ACH-exposure **Assess** segment + the tool registry + the
compliance self-check. Carried over verbatim from the combined ach_exposure server (ADR-063 split); only this
segment's tools plus the shared ``notify_pega`` handback are present.

Every handler except ``notify_pega`` is a pure function of its arguments — no clock, no randomness, no network —
so the same input always yields the same output. ``notify_pega`` is the one action tool with a side effect: it
POSTs the segment's handback to the mock Pega orchestrator (``PEGA_STUB_URL``), fail-soft.
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
ACTION_TOOLS = {"notify_pega"}


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
# Segment A — Assess & Recommend
# --------------------------------------------------------------------------- #

def classify_exposure(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    etype = str(_dig(args, "exposure_type", "") or "").lower()
    credit = _num(_dig(args, "credit_amount"))
    debit = _num(_dig(args, "debit_amount"))
    climit = _num(_dig(args, "credit_limit", 300000))
    dlimit = _num(_dig(args, "debit_limit", 200000))
    # Class: explicit type wins; else whichever side has the larger over-limit gap.
    if etype in ("credit", "debit"):
        cls = etype
    else:
        cls = "credit" if (credit - climit) >= (debit - dlimit) else "debit"
    amount = credit if cls == "credit" else debit
    limit = climit if cls == "credit" else dlimit
    overage = _num(_dig(args, "overage"), max(0.0, amount - limit))
    ratio = (overage / limit) if limit else 0.0
    severity = "severe" if ratio >= 0.5 else "material" if ratio > 0.0 else "within_tolerance"
    return {"case_id": case, "exposure_class": cls, "amount": amount, "limit": limit,
            "overage": round(overage, 2), "severity": severity}


def get_client_risk_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    company = _company(args)
    # Deterministic "profile" seeded by the company name — stable across runs.
    h = int(_hash("risk", company), 16)
    tier = ["low", "medium", "high"][h % 3]
    return {"case_id": case, "company": company, "risk_tier": tier,
            "standing": "watch" if tier == "high" else "good",
            "prior_exceptions": h % 5, "temp_limit_active": (h % 4 == 0)}


def recommend_disposition(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    severity = str(_dig(args, "severity", "material") or "material").lower()
    tier = str(_dig(args, "risk_tier", "medium") or "medium").lower()
    standing = str(_dig(args, "standing", "good") or "good").lower()
    # Simple, explainable policy.
    if severity == "severe" and tier == "high":
        rec, conf = "REJECT", 0.88
        why = "Severe overage on a high-risk client in watch standing — recommend rejecting and purging."
    elif severity in ("within_tolerance", "material") and tier in ("low", "medium") and standing == "good":
        rec, conf = "APPROVE", 0.82
        why = f"{severity.replace('_', ' ').title()} overage on a {tier}-risk client in good standing — recommend approving the release."
    else:
        rec, conf = "ROUTE_UW", 0.60
        why = f"{severity} overage with {tier} risk / {standing} standing is borderline — route to underwriting for a manual call."
    return {"case_id": case, "recommendation": rec, "confidence": conf, "rationale": why}


def draft_underwriting_message(args: Dict[str, Any]) -> Dict[str, Any]:
    case = _case_id(args)
    company = _company(args)
    cls = str(_dig(args, "exposure_class", "credit") or "credit")
    overage = _num(_dig(args, "overage"))
    rec = str(_dig(args, "recommendation", "ROUTE_UW") or "ROUTE_UW")
    rationale = str(_dig(args, "rationale", "") or "")
    subject = f"[ACH Exposure] {company} — {cls} exposure exceeded (case {case})"
    body = (
        f"Case {case}: {company} has breached its {cls} exposure limit by "
        f"${overage:,.2f}. Agent recommendation: {rec}. {rationale} "
        f"Please review and provide the RBO decision (approve to release / reject to purge)."
    )
    return {"case_id": case, "subject": subject, "body": body}


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
    _tool("classify_exposure", "Classify an ACH exposure exception as credit/debit and grade its severity from the overage.",
          S.CLASSIFY_EXPOSURE_INPUT, S.CLASSIFY_EXPOSURE_OUTPUT, classify_exposure),
    _tool("get_client_risk_profile", "Return the client's risk tier, standing, prior-exception count, and temp-limit status.",
          S.CLIENT_RISK_PROFILE_INPUT, S.CLIENT_RISK_PROFILE_OUTPUT, get_client_risk_profile),
    _tool("recommend_disposition", "Recommend APPROVE / REJECT / ROUTE_UW with a confidence and a plain-language rationale.",
          S.RECOMMEND_DISPOSITION_INPUT, S.RECOMMEND_DISPOSITION_OUTPUT, recommend_disposition),
    _tool("draft_underwriting_message", "Draft the exposure-exceeded underwriting message (subject + body) for the RBO underwriter.",
          S.DRAFT_UNDERWRITING_INPUT, S.DRAFT_UNDERWRITING_OUTPUT, draft_underwriting_message),
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
