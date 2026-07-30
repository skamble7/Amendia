# external.py
"""Thin, deterministic stand-ins for the external systems the dine-in process talks to
(the Kitchen Display System and the Point-of-Sale / card terminal). The capability handlers call
these so their outputs carry plausible, connected reference ids.

These are **NOT** Amendia capabilities and are deliberately kept out of the tool registry — they
exist only for realism, mirroring the wire server's ``external.py`` (P_Core / P_Cpty stand-ins).
Everything here is a pure function of its input: no clock, no randomness, no network.
"""
from __future__ import annotations

import hashlib


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# -- Kitchen Display System (the "kitchen" pool) -- #

def post_kitchen_ticket(ticket_id: str) -> str:
    """Fire a ticket to the KDS — returns the deterministic kitchen ticket reference."""
    return "KDS-" + _h("fire", ticket_id)[:12].upper()


# -- Point-of-Sale / card terminal (the "POS" pool) -- #

def post_payment(ticket_id: str) -> str:
    """Capture a payment at the POS — the settlement reference for a captured charge."""
    return "PAY-" + _h("charge", ticket_id)[:12].upper()


def send_guest_receipt(ticket_id: str) -> str:
    """Issue a receipt to the guest (email/SMS)."""
    return "RCPT-" + _h("receipt", ticket_id)[:12].upper()
