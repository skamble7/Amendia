# app/capabilities/screening.py
"""cap.screening.screen_party — a tiny read-only screen used by the native-reduce demo pack (ADR-038).

Produces one ``party_result`` from the envelope's creditor: a ``SANCTIONED`` marker in the name → a
``hit`` verdict, else ``clean`` (mirrors the sanctions stub's marker convention). Bound behind a
multi-instance activity, it yields a *list* of party_results that a ``reduce`` capability collapses.
"""
from __future__ import annotations

from typing import Any, Dict

ARTIFACT_KEY = "art.screening.party_result"
_SANCTION_MARKER = "SANCTIONED"


def screen_party(*, inputs: Dict[str, Any], envelope: Dict[str, Any], mode: str = "execute",
                 approved_action_ids=None) -> Dict[str, Any]:
    name = ((envelope.get("payment", {}) or {}).get("creditor", {}) or {}).get("name", "")
    verdict = "hit" if _SANCTION_MARKER in name.upper() else "clean"
    return {
        "outputs": {ARTIFACT_KEY: {"party": name or "unknown", "verdict": verdict}},
        "log": f"screened '{name}': {verdict}",
    }
