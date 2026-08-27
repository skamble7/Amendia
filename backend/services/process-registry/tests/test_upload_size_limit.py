"""413 on oversized BPMN upload — compounding-factor mitigation for the entity-expansion DoS
(scan 2026-08-19, C-2). The cap is configurable via REGISTRY_MAX_BPMN_UPLOAD_BYTES (config.MAX_BPMN_UPLOAD_BYTES).
The `client` fixture runs auth_disabled, so the role.process.owner guard passes and the size check is reached."""
from app.config import settings


async def test_oversized_bpmn_onboarding_returns_413(client):
    # attach_bpmn checks size BEFORE touching the session, so no session setup is needed.
    big = "<x/>" + "A" * (settings.MAX_BPMN_UPLOAD_BYTES + 1)
    r = await client.put("/onboarding/any-session/bpmn", json={"bpmn_xml": big})
    assert r.status_code == 413


async def test_at_limit_bpmn_not_size_rejected(client):
    # A payload at/under the limit must NOT be 413 (it proceeds; the missing session then yields a
    # non-413 error) — proves the gate rejects on SIZE only, not on every upload.
    ok_size = "A" * (settings.MAX_BPMN_UPLOAD_BYTES - 1024)
    r = await client.put("/onboarding/any-session/bpmn", json={"bpmn_xml": ok_size})
    assert r.status_code != 413
