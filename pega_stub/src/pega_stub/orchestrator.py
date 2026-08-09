# src/pega_stub/orchestrator.py
"""The mock Pega orchestration state machine for one ACH-exposure case.

Fires the three segment triggers (A → B → C), each stamped with the same ``case_id``, advancing on each
``notify_pega`` handback, then emits the ``process_completed`` close message that disposes the cohort. The
advance is driven by the case's OWN tracked step (robust to a missing/duplicated ``segment`` in the handback);
each segment advances exactly once (idempotent per (case_id, segment)).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import scenarios as S

logger = logging.getLogger(__name__)

SEGMENTS = ["A", "B", "C"]

# A submit fn: (trigger_type, schema_version, payload) -> trigger_id. Injected so tests use a fake store.
SubmitFn = Callable[..., Awaitable[str]]


def _canonical_segment(segment: Optional[str], completed: List[str]) -> Optional[str]:
    """Map a handback's (possibly missing/aliased) segment to A/B/C. When unmappable/missing, fall back to the
    next-expected segment (the pipeline is strictly in order), so a normal in-order handback still advances."""
    s = (segment or "").strip().lower()
    if s in ("a", "assess", "assess_exposure", "ach-exposure-assess", "segment_a"):
        return "A"
    if s in ("b", "enforce", "enforce_decision", "ach-decision-enforce", "segment_b"):
        return "B"
    if s in ("c", "closeout", "close_out", "ach-closeout", "segment_c"):
        return "C"
    if "assess" in s:
        return "A"
    if "enforce" in s or "decision" in s:
        return "B"
    if "close" in s:
        return "C"
    idx = len(completed)
    return SEGMENTS[idx] if idx < len(SEGMENTS) else None


class Orchestrator:
    def __init__(self, submit: SubmitFn) -> None:
        self._submit = submit
        self.cases: Dict[str, Dict[str, Any]] = {}

    # -- reads --
    def get(self, case_id: str) -> Optional[Dict[str, Any]]:
        return self.cases.get(case_id)

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self.cases.values(), key=lambda c: c["created_at"], reverse=True)

    # -- start --
    async def start_case(self, scenario: str, case_id: Optional[str] = None) -> Dict[str, Any]:
        if scenario not in S.SCENARIOS:
            raise ValueError(f"unknown scenario '{scenario}' (expected one of {sorted(S.SCENARIOS)})")
        case_id = case_id or f"case-{uuid.uuid4().hex[:10]}"
        if case_id in self.cases:
            return self.cases[case_id]  # idempotent start
        preset = S.SCENARIOS[scenario]
        case: Dict[str, Any] = {
            "case_id": case_id, "scenario": scenario, "status": "running", "step": "A",
            "completed": [], "history": [], "triggers": {},
            "company": preset["company"], "rbo_decision": None, "instruction": None, "outcome": None,
            "created_at": _seq(),
        }
        self.cases[case_id] = case
        tid = await self._submit(
            trigger_type=S.TRIGGER_TYPE["A"], schema_version=S.SCHEMA_VERSION["A"],
            payload=S.segment_a_payload(case_id, preset))
        case["triggers"]["A"] = tid
        case["history"].append({"op": "submitted", "segment": "A", "trigger_id": tid})
        logger.info("case %s started (scenario=%s) → segment A trigger %s", case_id, scenario, tid)
        return case

    # -- advance on handback --
    async def handback(self, case_id: str, segment: Optional[str], result: Any) -> Optional[Dict[str, Any]]:
        case = self.cases.get(case_id)
        if case is None:
            return None
        if case["status"] == "closed":
            return case  # already drained — no-op
        completed: List[str] = case["completed"]
        canonical = _canonical_segment(segment, completed)
        if canonical is None or canonical in completed:
            logger.info("case %s: duplicate/late handback (segment=%s) — no-op", case_id, segment)
            return case  # idempotent per (case_id, segment)

        completed.append(canonical)
        case["history"].append({"op": "handback", "segment": canonical, "result": result})
        n = len(completed)
        preset = S.SCENARIOS[case["scenario"]]

        if n == 1:  # Segment A done → decide + fire Segment B
            case["rbo_decision"] = _derive_rbo(result, preset)
            case["recommendation"] = _recommendation(result)
            tid = await self._submit(
                trigger_type=S.TRIGGER_TYPE["B"], schema_version=S.SCHEMA_VERSION["B"],
                payload=S.segment_b_payload(case_id, case["rbo_decision"]))
            case["triggers"]["B"] = tid
            case["step"] = "B"
            case["history"].append({"op": "submitted", "segment": "B", "trigger_id": tid,
                                    "rbo_decision": case["rbo_decision"]})
        elif n == 2:  # Segment B done → fire Segment C (instruction derived from the decision)
            case["instruction"] = "release" if case["rbo_decision"] == "approve" else "purge"
            tid = await self._submit(
                trigger_type=S.TRIGGER_TYPE["C"], schema_version=S.SCHEMA_VERSION["C"],
                payload=S.segment_c_payload(case_id, case["instruction"]))
            case["triggers"]["C"] = tid
            case["step"] = "C"
            case["history"].append({"op": "submitted", "segment": "C", "trigger_id": tid,
                                    "instruction": case["instruction"]})
        elif n == 3:  # Segment C done → emit the close message; the cohort drains to closed
            case["outcome"] = "Released" if case["instruction"] == "release" else "Purged"
            tid = await self._submit(
                trigger_type=S.TRIGGER_TYPE["close"], schema_version=S.SCHEMA_VERSION["close"],
                payload=S.close_payload(case_id, case["outcome"]))
            case["triggers"]["close"] = tid
            case["step"] = "closed"
            case["status"] = "closed"
            case["history"].append({"op": "submitted", "segment": "close", "trigger_id": tid,
                                    "outcome": case["outcome"]})
        return case


def _recommendation(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        rec = result.get("recommendation")
        return str(rec) if rec is not None else None
    return None


def _derive_rbo(result: Any, preset: Dict[str, Any]) -> str:
    """Segment B's decision: honour Segment A's recommendation when it's decisive; ROUTE_UW/absent → the
    scenario's hands-free preset (the underwriter's default call)."""
    rec = (_recommendation(result) or "").upper()
    if rec == "APPROVE":
        return "approve"
    if rec == "REJECT":
        return "reject"
    return preset["rbo_decision"]


_counter = {"n": 0}


def _seq() -> int:
    """Monotonic creation order (no wall-clock dependency — deterministic in tests)."""
    _counter["n"] += 1
    return _counter["n"]
