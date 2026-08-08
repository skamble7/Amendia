# app/routers/packs.py
"""ProcessPack onboarding: submit → upload BPMN → validate → activate → deprecate."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from amendia_auth import AuthenticatedUser, require_roles

from amendia_contracts.process_pack import ProcessPackManifest
from app.events.publisher import emit_pack_lifecycle
from app.config import settings
from app.models.onboarding import RollbackPackRequest
from app.dal.base import DuplicateError
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.onboarding_repo import OnboardingRepository
from app.dal.pack_repo import ProcessPackRepository
from app.deps import (
    get_artifact_schema_repo,
    get_bpmn_repo,
    get_capability_repo,
    get_onboarding_repo,
    get_pack_repo,
    get_publisher,
    get_resolver,
    get_validator,
)
from app.services.activation import resolve_pins
from app.services.deletion import delete_versions
from app.services.resolver import ResolveService
from app.validation.bpmn import compute_sha256
from app.validation.pack_validator import PackValidator

router = APIRouter(prefix="/packs", tags=["packs"])

# Pack authoring mutations are process-owner only.
_OWNER = Depends(require_roles("role.process.owner"))


def _load_sample_envelopes() -> List[dict]:
    d = Path(settings.SEED_DIR) / "sample-exception"
    if not d.exists():
        return []
    return [json.loads(f.read_text()) for f in sorted(d.glob("*.json"))]


async def _require_pack(repo: ProcessPackRepository, pack_key: str, version: str) -> ProcessPackManifest:
    manifest = await repo.get(pack_key, version)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Unknown pack {pack_key}@{version}")
    return manifest


@router.post("", response_model=ProcessPackManifest, status_code=201, dependencies=[_OWNER])
async def submit_pack(manifest: ProcessPackManifest, repo: ProcessPackRepository = Depends(get_pack_repo)):
    if manifest.status.value != "draft":
        raise HTTPException(status_code=422, detail="submitted pack must have status 'draft'")
    if any(rc.resolved is not None for rc in manifest.requires_capabilities):
        raise HTTPException(status_code=422, detail="pins ('resolved') are registry-assigned; omit them on submit")
    try:
        return await repo.insert(manifest)
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/{pack_key}/{version}/bpmn", dependencies=[_OWNER])
async def upload_bpmn(
    pack_key: str, version: str, request: Request,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    bpmn_repo: BpmnRepository = Depends(get_bpmn_repo),
):
    manifest = await _require_pack(repo, pack_key, version)
    # Uploading is part of assembling the draft; a re-upload while validated is a
    # mutation that drops the pack back to draft. Not allowed once active/deprecated.
    if manifest.status.value not in ("draft", "validated"):
        raise HTTPException(status_code=409, detail="BPMN can only be uploaded while draft/validated")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="empty BPMN body")
    xml = body.decode("utf-8")
    sha = compute_sha256(xml)
    await bpmn_repo.upsert(pack_key, version, xml=xml, sha256=sha)
    await repo.set_bpmn_sha(pack_key, version, sha)  # keeps status 'draft'
    return {"pack_key": pack_key, "version": version, "bpmn_sha256": sha}


@router.post("/{pack_key}/{version}/validate", dependencies=[_OWNER])
async def validate_pack(
    pack_key: str, version: str,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    bpmn_repo: BpmnRepository = Depends(get_bpmn_repo),
    validator: PackValidator = Depends(get_validator),
):
    manifest = await _require_pack(repo, pack_key, version)
    if manifest.status.value not in ("draft", "validated"):
        raise HTTPException(status_code=409, detail=f"cannot validate a pack in status '{manifest.status.value}'")
    bpmn_xml = await bpmn_repo.get_xml(pack_key, version)
    report = await validator.validate(manifest, bpmn_xml, sample_envelopes=_load_sample_envelopes())
    await repo.save_validation_report(pack_key, version, report.model_dump(mode="json"))
    await repo.set_status(pack_key, version, "validated" if report.ok else "draft")
    return report


@router.post("/{pack_key}/{version}/activate", response_model=ProcessPackManifest, dependencies=[_OWNER])
async def activate_pack(
    pack_key: str, version: str,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    bpmn_repo: BpmnRepository = Depends(get_bpmn_repo),
    validator: PackValidator = Depends(get_validator),
    resolver: ResolveService = Depends(get_resolver),
    cap_repo: CapabilityRepository = Depends(get_capability_repo),
    schema_repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
    actor: AuthenticatedUser = _OWNER,
    publisher=Depends(get_publisher),
):
    manifest = await _require_pack(repo, pack_key, version)
    if manifest.status.value != "validated":
        raise HTTPException(status_code=422, detail=f"activate requires status 'validated', got '{manifest.status.value}'")
    # defense in depth: re-validate
    bpmn_xml = await bpmn_repo.get_xml(pack_key, version)
    report = await validator.validate(manifest, bpmn_xml, sample_envelopes=_load_sample_envelopes())
    await repo.save_validation_report(pack_key, version, report.model_dump(mode="json"))
    if not report.ok:
        await repo.set_status(pack_key, version, "draft")
        raise HTTPException(status_code=422, detail={"message": "re-validation failed", "errors": report.error_codes()})

    # ADR-027 Phase 2.5: derive the pack's minimum required execution profile from its BPMN and pin
    # it in the resolution sidecar so the runtime can refuse a pack it can't run (at load, not mid-flight).
    from amendia_bpmn import parse as _parse, required_profile as _required_profile
    _model, _ = _parse(bpmn_xml, manifest.process.process_id)
    prof = _required_profile(_model) if _model is not None else "common_subset"
    resolution, resolved_caps = await resolve_pins(manifest, cap_repo, schema_repo,
                                                   required_execution_profile=prof, pack_repo=repo)
    activated = await repo.activate(pack_key, version, resolved_caps=resolved_caps, resolution=resolution.to_doc())
    resolver.invalidate()
    await emit_pack_lifecycle(publisher, pack_key=pack_key, version=version, op="publish",
                              actor=getattr(actor, "amendia_user_id", "unknown"))
    return activated


@router.post("/{pack_key}/{version}/deprecate", response_model=ProcessPackManifest, dependencies=[_OWNER])
async def deprecate_pack(
    pack_key: str, version: str,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    resolver: ResolveService = Depends(get_resolver),
    actor: AuthenticatedUser = _OWNER,
    publisher=Depends(get_publisher),
):
    manifest = await _require_pack(repo, pack_key, version)
    if manifest.status.value != "active":
        raise HTTPException(status_code=422, detail=f"deprecate requires status 'active', got '{manifest.status.value}'")
    await repo.set_status(pack_key, version, "deprecated")
    resolver.invalidate()
    await emit_pack_lifecycle(publisher, pack_key=pack_key, version=version, op="deprecate",
                              actor=getattr(actor, "amendia_user_id", "unknown"))
    return await repo.get(pack_key, version)


@router.post("/{pack_key}/rollback", response_model=ProcessPackManifest, dependencies=[_OWNER])
async def rollback_pack(
    pack_key: str, req: RollbackPackRequest,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    resolver: ResolveService = Depends(get_resolver),
    actor: AuthenticatedUser = _OWNER,
    publisher=Depends(get_publisher),
):
    """ADR-056: make a prior (non-draft) version live again. Because the resolver prefers the highest ACTIVE
    version, the currently-active one MUST be deprecated for the rollback to take effect — so this deprecates it
    and activates ``to_version``. The target keeps its stored capability resolution (valid when first published)."""
    versions = await repo.list_versions(pack_key)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown pack: {pack_key}")
    target = next((m for m in versions if m.version == req.to_version), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"{pack_key}@{req.to_version} not found")
    if target.status.value == "draft":
        raise HTTPException(status_code=422, detail="cannot roll back to a draft version")
    for m in versions:                                          # deprecate whatever is currently live for this key
        if m.status.value == "active" and m.version != req.to_version:
            await repo.set_status(pack_key, m.version, "deprecated")
    await repo.set_status(pack_key, req.to_version, "active")
    resolver.invalidate()
    await emit_pack_lifecycle(publisher, pack_key=pack_key, version=req.to_version, op="rollback",
                              actor=getattr(actor, "amendia_user_id", "unknown"))
    return await repo.get(pack_key, req.to_version)


# -- deletion (ADR-061): force-delete a version or the whole pack (process-owner only, audit-first) --
@router.delete("/{pack_key}/{version}", dependencies=[_OWNER])
async def delete_pack_version(
    pack_key: str, version: str,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    bpmn_repo: BpmnRepository = Depends(get_bpmn_repo),
    cap_repo: CapabilityRepository = Depends(get_capability_repo),
    schema_repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
    onboarding_repo: OnboardingRepository = Depends(get_onboarding_repo),
    resolver: ResolveService = Depends(get_resolver),
    actor: AuthenticatedUser = _OWNER,
    publisher=Depends(get_publisher),
):
    """ADR-061: physically remove ONE pack version and everything it owns (sidecars + ADR-060 caps/schemas +
    committed sessions). Force-delete at any status (no deprecate-first, no liveness gate). Audit-first."""
    manifest = await _require_pack(repo, pack_key, version)  # 404 if absent
    return await delete_versions(
        pack_key=pack_key, versions=[manifest],
        actor=getattr(actor, "amendia_user_id", "unknown"), whole_pack=False,
        pack_repo=repo, bpmn_repo=bpmn_repo, cap_repo=cap_repo, schema_repo=schema_repo,
        onboarding_repo=onboarding_repo, publisher=publisher, resolver=resolver,
    )


@router.delete("/{pack_key}", dependencies=[_OWNER])
async def delete_whole_pack(
    pack_key: str,
    repo: ProcessPackRepository = Depends(get_pack_repo),
    bpmn_repo: BpmnRepository = Depends(get_bpmn_repo),
    cap_repo: CapabilityRepository = Depends(get_capability_repo),
    schema_repo: ArtifactSchemaRepository = Depends(get_artifact_schema_repo),
    onboarding_repo: OnboardingRepository = Depends(get_onboarding_repo),
    resolver: ResolveService = Depends(get_resolver),
    actor: AuthenticatedUser = _OWNER,
    publisher=Depends(get_publisher),
):
    """ADR-061: physically remove EVERY version of ``pack_key`` (one ``delete`` audit event per version)."""
    versions = await repo.list_versions(pack_key)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown pack: {pack_key}")
    return await delete_versions(
        pack_key=pack_key, versions=versions,
        actor=getattr(actor, "amendia_user_id", "unknown"), whole_pack=True,
        pack_repo=repo, bpmn_repo=bpmn_repo, cap_repo=cap_repo, schema_repo=schema_repo,
        onboarding_repo=onboarding_repo, publisher=publisher, resolver=resolver,
    )


# -- reads --
@router.get("", response_model=List[ProcessPackManifest])
async def list_packs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ProcessPackRepository = Depends(get_pack_repo),
):
    return await repo.list(status=status, limit=limit, offset=offset)


@router.get("/{pack_key}", response_model=List[ProcessPackManifest])
async def list_pack_versions(pack_key: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    versions = await repo.list_versions(pack_key)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Unknown pack: {pack_key}")
    return versions


@router.get("/{pack_key}/{version}", response_model=ProcessPackManifest)
async def get_pack(pack_key: str, version: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    return await _require_pack(repo, pack_key, version)


@router.get("/{pack_key}/{version}/bpmn")
async def get_pack_bpmn(pack_key: str, version: str, bpmn_repo: BpmnRepository = Depends(get_bpmn_repo)):
    xml = await bpmn_repo.get_xml(pack_key, version)
    if xml is None:
        raise HTTPException(status_code=404, detail=f"No BPMN for {pack_key}@{version}")
    return Response(content=xml, media_type="application/xml")


@router.get("/{pack_key}/{version}/validation-report")
async def get_validation_report(pack_key: str, version: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    report = await repo.get_validation_report(pack_key, version)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No validation report for {pack_key}@{version}")
    return report


@router.get("/{pack_key}/{version}/resolution")
async def get_pack_resolution(pack_key: str, version: str, repo: ProcessPackRepository = Depends(get_pack_repo)):
    resolution = await repo.get_resolution(pack_key, version)
    if resolution is None:
        raise HTTPException(status_code=404, detail=f"No resolution for {pack_key}@{version} (activate first)")
    return resolution
