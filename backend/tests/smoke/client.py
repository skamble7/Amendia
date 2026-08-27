# backend/tests/smoke/client.py
"""Thin sync HTTP helpers for the smoke suite: readiness checks, Keycloak token minting (cached), the
per-persona identity lookup (for SoD), and a poll-until helper. Generalizes the token/poll plumbing from
``tools/demo_wire_repair.sh`` (mint via the dev CLI client / password grant; poll to a terminal state).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import httpx

from .config import SmokeConfig

TERMINAL = {"completed", "failed"}


def reachable(url: str, *, timeout: float = 4.0) -> bool:
    """A service is 'reachable' if it answers HTTP at all (even 401/404) — only a transport error is 'down'."""
    try:
        httpx.get(url, timeout=timeout)
        return True
    except httpx.HTTPError:
        return False


def stack_down_reason(cfg: SmokeConfig) -> Optional[str]:
    """None when every core service is reachable; else a human message naming what's down."""
    down = [name for name, url in cfg.core_health().items() if not reachable(url)]
    if not down:
        return None
    return (f"stack not reachable ({', '.join(down)} down) — bring it up: "
            f"`docker compose -f backend/deploy/docker-compose.yml up -d` (+ pega_stub compose for ACH)")


class Tokens:
    """Mints + caches a Keycloak bearer per persona (username == persona), and resolves each persona's
    Amendia user id via the identity ``/me`` endpoint (for SoD exclusion checks)."""

    def __init__(self, cfg: SmokeConfig, http: httpx.Client) -> None:
        self._cfg = cfg
        self._http = http
        self._tokens: Dict[str, str] = {}
        self._user_ids: Dict[str, Optional[str]] = {}

    def get(self, persona: str) -> str:
        if persona not in self._tokens:
            r = self._http.post(self._cfg.token_url, data={
                "grant_type": "password", "client_id": self._cfg.cli_client,
                "client_secret": self._cfg.cli_secret, "username": persona,
                "password": self._cfg.dev_password, "scope": "openid",
            })
            if r.status_code != 200:
                raise TokenError(f"could not mint a token for persona '{persona}' "
                                 f"(HTTP {r.status_code}) — is '{persona}' a user in realm "
                                 f"'{self._cfg.realm}'? Seed the persona or override the scenario's hitl map.")
            self._tokens[persona] = r.json()["access_token"]
        return self._tokens[persona]

    def headers(self, persona: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.get(persona)}"}

    def user_id(self, persona: str) -> Optional[str]:
        if persona not in self._user_ids:
            try:
                r = self._http.get(f"{self._cfg.identity}/me", headers=self.headers(persona))
                self._user_ids[persona] = r.json().get("amendia_user_id") if r.status_code == 200 else None
            except httpx.HTTPError:
                self._user_ids[persona] = None
        return self._user_ids[persona]


class TokenError(RuntimeError):
    """A persona could not be authenticated — the caller skips the scenario with this message."""


def poll(
    http: httpx.Client, url: str, extract: Callable[[dict], Any], want: Any, *,
    headers: Optional[Dict[str, str]] = None, timeout_s: float = 120.0, interval_s: float = 1.0,
    terminal: bool = False,
) -> Any:
    """Poll ``url`` until ``extract(json) == want`` (or, when ``terminal``, until it's in TERMINAL). Returns
    the matched value, or None on timeout. Transport/JSON hiccups are swallowed and retried."""
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        try:
            r = http.get(url, headers=headers)
            last = extract(r.json()) if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            last = None
        if last == want or (terminal and last in TERMINAL):
            return last
        time.sleep(interval_s)
    return last if (terminal and last in TERMINAL) else None
