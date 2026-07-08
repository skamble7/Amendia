# app/capabilities/wire_repair/_common.py
"""Helpers shared by the simulated wire-repair capabilities.

Every capability is a pure, deterministic, envelope-aware function with the
signature ``run(*, inputs, envelope, mode="execute", approved_action_ids=None)``
returning either:
  * ``{"outputs": {artifact_key: data, ...}, "log": str}`` (execute mode), or
  * ``{"proposed_actions": [...], "log": str}``           (propose mode).

Outputs are keyed by artifact_key so the task runner can map them to binding
output names and validate against the pinned schema. NO real side effects — the
side-effectful capabilities log loudly instead.
"""
from __future__ import annotations

from typing import Any, Dict


def drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively drop keys whose value is None (schemas forbid null on typed props)."""
    if isinstance(d, dict):
        return {k: drop_none(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [drop_none(v) for v in d]
    return d


def correct_account(account_id: str) -> str:
    """Deterministic 'repaired' account id: transpose the last two digits.

    Mirrors the POC scenario (a digit transposition in the creditor account).
    """
    if account_id and len(account_id) >= 2:
        return account_id[:-2] + account_id[-1] + account_id[-2]
    return (account_id or "") + "0"


def reason_codes(envelope: Dict[str, Any]) -> list[str]:
    return list(envelope.get("reason_codes", []) or [])
