# external.py
"""Thin, deterministic stand-ins for the external systems the reference process talks to
(Core Banking / Payment Rails, Counterparty Banks). The capability handlers call these so
their outputs carry plausible, connected reference ids.

These are **NOT** Amendia capabilities and are deliberately kept out of the tool registry —
they exist only for realism, mirroring the BPMN's external pools (P_Core, P_Cpty). Everything
here is a pure function of its input: no clock, no randomness, no network.
"""
from __future__ import annotations

import hashlib
from typing import Dict


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# -- Core Banking / Payment Rails (P_Core) -- #

def fetch_payment(exception_id: str) -> Dict[str, str]:
    """Core Banking lookup — returns a deterministic core payment reference."""
    return {"core_ref": "CORE-" + _h("fetch", exception_id)[:10].upper()}


def post_payment_release(exception_id: str) -> str:
    """Payment Rails release — the settlement/release reference for an applied repair."""
    return "REL-" + _h("release", exception_id)[:12].upper()


def post_return(exception_id: str) -> str:
    """Payment Rails return — the reference for an executed return."""
    return "RET-" + _h("return", exception_id)[:12].upper()


# -- Counterparty Banks (P_Cpty) -- #

def send_pacs008(exception_id: str) -> str:
    """Advice to the beneficiary bank (pacs.008)."""
    return "PACS008-" + _h("pacs008", exception_id)[:12].upper()


def send_pacs004(exception_id: str) -> str:
    """Payment return message (pacs.004)."""
    return "PACS004-" + _h("pacs004", exception_id)[:12].upper()


def send_rfi(exception_id: str) -> str:
    """Request-for-information to the counterparty (camt.026)."""
    return "RFI-" + _h("rfi", exception_id)[:12].upper()
