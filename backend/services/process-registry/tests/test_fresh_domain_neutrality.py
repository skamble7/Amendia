# tests/test_fresh_domain_neutrality.py
"""ADR-047 neutrality invariant (registry half) — a fresh domain needs DATA, not code.

Onboards a brand-new domain with zero payments overlap — ``widget-qa`` (a manufacturing QA process, in the
``cap.widgetqa.*`` / ``art.widgetqa.*`` namespaces) — through the REAL registry front door
(schema→cap→manifest→bpmn→validate→activate) and asserts it reaches ACTIVE. The pack is pure fixture data:
no platform code is added or changed. Paired with ``agent-runtime/tests/test_fresh_domain_neutrality.py``
(which executes the same pack on the generic runtime), this locks the "new domain = data, not code" invariant
across the registry→runtime seam a payments-flavored test can't prove.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.pack_repo import ProcessPackRepository
from app.db.mongo import (
    ARTIFACT_SCHEMAS, BPMN_DOCUMENTS, CAPABILITIES, PACK_RESOLUTIONS, PACK_ROLES,
    PROCESS_PACKS, VALIDATION_REPORTS, create_indexes,
)
from app.seeding.onboard_seed import onboard

WIDGET_QA = Path(__file__).resolve().parents[2] / "agent-runtime" / "tests" / "fixtures" / "widget-qa"
_PAYMENTS_TERMS = ("wire", "repair", "dossier", "sanction", "beneficiary", "payment", "pacs")


async def test_fresh_domain_pack_onboards_validates_activates():
    db = AsyncMongoMockClient()["neutrality_widgetqa"]
    await create_indexes(db)
    result = await onboard(
        WIDGET_QA,
        CapabilityRepository(db[CAPABILITIES]),
        ArtifactSchemaRepository(db[ARTIFACT_SCHEMAS]),
        ProcessPackRepository(db[PROCESS_PACKS], db[VALIDATION_REPORTS],
                              db[PACK_RESOLUTIONS], db[PACK_ROLES]),
        BpmnRepository(db[BPMN_DOCUMENTS]),
    )
    assert result["validation"]["ok"], f"widget-qa NOT registry-valid: {result['validation']['errors']}"
    assert "ACTIVE" in (result["pack"] or ""), f"widget-qa did not activate: {result['pack']}"


def test_fresh_domain_is_pure_data_not_code():
    # The proof of neutrality: a new domain is entirely fixture data — no Python, so no platform code.
    py = [p for p in WIDGET_QA.rglob("*.py")]
    assert not py, f"a fresh domain must be data, not code — found Python in the fixture: {py}"


def test_fresh_domain_has_zero_payments_overlap():
    # Names must be genuinely fresh — a payments-flavored pack wouldn't prove neutrality.
    ids = " ".join(p.name for p in WIDGET_QA.rglob("*.json")).lower()
    leaked = [t for t in _PAYMENTS_TERMS if t in ids]
    assert not leaked, f"widget-qa filenames overlap payments domain terms: {leaked}"


def test_registry_carries_no_widgetqa_code():
    # The enforceable "data, not code" guard (more robust than a git diff): the registry app/ image contains
    # ZERO widget-qa-specific code. If onboarding a new domain ever required an app/ change, this fails.
    app_dir = Path(__file__).resolve().parents[1] / "app"
    hits = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
            if "widgetqa" in p.read_text().lower() or "widget_qa" in p.read_text().lower()]
    assert not hits, f"registry image references the fresh domain — it should need no code: {hits}"
