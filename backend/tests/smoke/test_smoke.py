# backend/tests/smoke/test_smoke.py
"""The one parametrized smoke test — data-driven by the scenario corpus. NOTHING domain-specific lives here:
per-domain values live in ``scenarios/*.yaml``, per-mechanism logic in the keyed drivers. Adding a domain is a
new spec file, not a change to this test.

Happy-path, full-stack: preflight the stack + packs → fire the domain's real trigger → drive its HITL gates →
assert the instance (single) or the cohort (segmented) reaches the expected terminal outcome. A stack/pack/
persona that isn't there is a **skip with guidance**, never a confusing failure."""
from __future__ import annotations

import time
from typing import Optional

import pytest

from .client import TokenError, poll
from .config import SmokeConfig
from .drivers import DriverError, Handle, fire
from .hitl import resolve_open_for
from .scenarios import Scenario, load_scenarios

SCENARIOS = load_scenarios()


def _json(http, url: str, headers) -> Optional[dict]:
    try:
        r = http.get(url, headers=headers)
        return r.json() if r.status_code == 200 else None
    except (ValueError, Exception):  # noqa: BLE001 - best-effort read; None on any hiccup
        return None


def _active_pack_keys(cfg: SmokeConfig, http, headers) -> Optional[set]:
    try:
        r = http.get(f"{cfg.registry}/packs?status=active&limit=200", headers=headers)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    return {p.get("pack_key") for p in r.json()}


def _drive_single(cfg: SmokeConfig, http, tokens, sc: Scenario, handle: Handle) -> None:
    hdr = tokens.headers(sc.hitl.default_persona)
    ing_url = f"{cfg.ingestor}/ingestions/{handle.trigger_id}"
    status = poll(http, ing_url, lambda j: j.get("status"), "accepted",
                  headers=hdr, timeout_s=min(90.0, sc.timeout_s))
    assert status == "accepted", (
        f"{sc.domain}: trigger {handle.trigger_id} did not reach ingestion 'accepted' (got {status!r}) — "
        f"is the pack onboarded + its triage matching?")
    ing = _json(http, ing_url, hdr) or {}
    pid = ing.get("process_instance_id")
    assert pid, f"{sc.domain}: ingestion has no process_instance_id"
    pack = (ing.get("resolution") or {}).get("pack_key")
    assert pack in sc.pack_keys, f"{sc.domain}: resolved pack {pack!r} not in expected {sc.pack_keys}"

    inst_url = f"{cfg.runtime}/instances/{pid}"
    deadline = time.monotonic() + sc.timeout_s
    while time.monotonic() < deadline:
        st = (_json(http, inst_url, hdr) or {}).get("status")
        if st in ("completed", "failed"):
            break
        resolve_open_for(cfg, http, tokens, sc, pid, {"correlation": handle.correlation})
        time.sleep(2)
    final = (_json(http, inst_url, hdr) or {}).get("status")
    assert final == sc.expect.instance_status, (
        f"{sc.domain}: instance {pid} ended {final!r}, expected {sc.expect.instance_status!r}")


def _drive_cohort(cfg: SmokeConfig, http, tokens, sc: Scenario, handle: Handle) -> None:
    hdr = tokens.headers(sc.hitl.default_persona)
    coh_url = f"{cfg.glea}/cohorts/by-correlation/{handle.correlation}"
    want = sc.expect.cohort or {}
    want_state = want.get("state", "closed")
    deadline = time.monotonic() + sc.timeout_s
    detail: Optional[dict] = None
    while time.monotonic() < deadline:
        detail = _json(http, coh_url, hdr)
        for m in (detail or {}).get("roster", []):
            pid = m.get("process_instance_id")
            if pid:
                resolve_open_for(cfg, http, tokens, sc, pid, {"correlation": handle.correlation})
        if detail and detail.get("state") == want_state:
            break
        time.sleep(2)

    assert detail, (f"{sc.domain}: GLEA observed no cohort for {handle.correlation!r} — is the cohort "
                    f"definition registered and its members onboarded?")
    assert detail.get("state") == want_state, (
        f"{sc.domain}: cohort {handle.correlation} state {detail.get('state')!r}, expected {want_state!r}")
    assert (detail.get("rollup") or {}).get("failed", 0) == 0, (
        f"{sc.domain}: cohort {handle.correlation} has failed members: {detail.get('rollup')}")
    if "outcome" in want:
        assert detail.get("outcome") == want["outcome"], (
            f"{sc.domain}: cohort outcome {detail.get('outcome')!r}, expected {want['outcome']!r}")


@pytest.mark.smoke
@pytest.mark.parametrize("sc", SCENARIOS, ids=[s.domain for s in SCENARIOS])
def test_corpus_smoke(sc: Scenario, cfg: SmokeConfig, http, tokens) -> None:
    if sc.skip:
        pytest.skip(f"{sc.domain}: {sc.skip_reason or 'spec marked skip'}")

    # Personas mintable? (a missing dev user → skip with guidance, not a failure)
    try:
        for persona in sc.persona_pool:
            tokens.get(persona)
    except TokenError as exc:
        pytest.skip(str(exc))

    # Packs onboarded? (the smoke runs against an already-onboarded stack)
    active = _active_pack_keys(cfg, http, tokens.headers(sc.hitl.default_persona))
    if active is None:
        pytest.skip(f"{sc.domain}: could not read {cfg.registry}/packs — is the registry up + token valid?")
    missing = [k for k in sc.pack_keys if k not in active]
    if missing:
        pytest.skip(f"{sc.domain}: onboard {missing} first (not active in the registry)")

    # Fire the trigger (driver keyed by trigger.kind). A down driver-service (pega_stub) → skip, not fail.
    try:
        handle = fire(cfg, http, tokens, sc)
    except (DriverError, TokenError) as exc:
        msg = str(exc)
        if "unreachable" in msg or "down" in msg:
            pytest.skip(f"{sc.domain}: {msg}")
        pytest.fail(f"{sc.domain}: {msg}")

    if sc.expect.cohort:
        _drive_cohort(cfg, http, tokens, sc, handle)
    else:
        _drive_single(cfg, http, tokens, sc, handle)
