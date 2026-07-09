# amendia_auth/errors.py
"""Typed auth failures.

``AuthError`` is raised by the validator and resolver on any authentication
problem (bad signature, wrong issuer/audience, expired token, resolution
failure). The FastAPI layer maps it to a 401/403 — it never leaks the token.
"""
from __future__ import annotations


class AuthError(Exception):
    """An authentication step failed. ``reason`` is a short machine slug
    (e.g. ``invalid_signature``, ``wrong_issuer``, ``expired``); it is safe to
    surface in a ``WWW-Authenticate`` error detail but never contains the token."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
