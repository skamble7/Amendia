# tests/test_cb1_staging_bpmn_cleanup.py
"""CB-1 — onboarding-draft BPMN (`__onb__<session>`) must not orphan in bpmn_documents.

Draft BPMN is staged under a per-session key while the wizard runs; commit re-keys it to the real pack and
session-delete drops the draft. Neither used to remove the staging row, so `__onb__…` rows accumulated forever.
These cover: (1) session-delete purges the draft; (2) the startup sweep clears pre-existing orphans while
keeping in-progress drafts. The commit path is covered in test_onboarding_fullset.py::test_e2e_message_pack_onboards_to_active.
"""
import pytest

from app.db.mongo import BPMN_DOCUMENTS, ONBOARDING_SESSIONS
from app.models.onboarding import AttachBpmnRequest, CreateSessionRequest
from app.services.onboarding import purge_orphaned_staging_bpmn
from tests.conftest import MCP_BPMN

OWNER = "usr-owner"


async def test_session_delete_purges_staging_bpmn(onboarding_service, bpmn_repo):
    s = await onboarding_service.create(
        CreateSessionRequest(pack_key="mcp-screen", version="1.0.0", title="t"), owner=OWNER)
    s = await onboarding_service.attach_bpmn(
        s.session_id, AttachBpmnRequest(bpmn_xml=MCP_BPMN), owner=OWNER)
    staging = f"__onb__{s.session_id}"
    assert await bpmn_repo.get_xml(staging, "1.0.0") is not None      # draft was staged

    await onboarding_service.delete(s.session_id, owner=OWNER)
    assert await bpmn_repo.get_xml(staging, "1.0.0") is None          # CB-1: draft dropped on delete


async def test_startup_sweep_purges_orphans_but_keeps_in_progress(db):
    bpmn, sessions = db[BPMN_DOCUMENTS], db[ONBOARDING_SESSIONS]
    # three staging drafts + one real pack; two sessions (one committed, one still assembling), one gone.
    await bpmn.insert_many([
        {"pack_key": "__onb__s-absent", "version": "1.0.0", "xml": "<x/>"},   # no session   → orphan
        {"pack_key": "__onb__s-done", "version": "1.0.0", "xml": "<x/>"},     # committed     → orphan
        {"pack_key": "__onb__s-live", "version": "1.0.0", "xml": "<x/>"},     # in progress   → keep
        {"pack_key": "wire-standard", "version": "1.0.0", "xml": "<x/>"},     # real pack     → untouched
    ])
    await sessions.insert_many([
        {"session_id": "s-done", "state": "completed"},
        {"session_id": "s-live", "state": "assembled"},
    ])

    purged = await purge_orphaned_staging_bpmn(bpmn, sessions)
    assert purged == 2

    remaining = set(await bpmn.distinct("pack_key"))
    assert remaining == {"__onb__s-live", "wire-standard"}           # in-progress draft + real pack survive

    # idempotent: a second sweep purges nothing.
    assert await purge_orphaned_staging_bpmn(bpmn, sessions) == 0
