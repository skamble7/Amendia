# app/services/activation.py
"""Resolve a validated pack's ranges to exact pins at activation.

Produces the ``Resolution`` sub-doc (capability + artifact + per-binding pins) plus a
capability_id→version map used to fill ``requires_capabilities[].resolved``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from packaging.version import Version

from amendia_bpmn import normalize_profile, profile_rank
from amendia_contracts.process_pack import ProcessPackManifest
from amendia_contracts.semver import satisfies
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.models.registry import ResolvedBinding, ResolvedCall, ResolvedIO, Resolution


async def _pin_capability(repo: CapabilityRepository, ref) -> Optional[str]:
    active = [v for v in await repo.list_by_id(ref.ref_id)
              if v.status.value == "active" and ref.matches(v.version)]
    if not active:
        return None
    return max(active, key=lambda v: Version(v.version)).version


async def _pin_pack(pack_repo: Any, pack_key: str, spec: str) -> Optional[str]:
    """ADR-039: pin a callee pack ``pack_key@spec`` to the highest **active** version satisfying the
    range (mirrors ``_pin_capability``). ``None`` when nothing active satisfies it → the caller sees
    ``call_activity_pack_unresolved``."""
    active = [m for m in await pack_repo.list_versions(pack_key)
              if m.status.value == "active" and satisfies(m.version, spec)]
    if not active:
        return None
    return max(active, key=lambda m: Version(m.version)).version


async def _pin_artifact(repo: ArtifactSchemaRepository, ref) -> Optional[str]:
    active = [v for v in await repo.list_by_key(ref.ref_id)
              if v.status.value == "active" and ref.matches(v.version)]
    if not active:
        return None
    return max(active, key=lambda v: Version(v.version)).version


async def resolve_pins(
    manifest: ProcessPackManifest,
    cap_repo: CapabilityRepository,
    schema_repo: ArtifactSchemaRepository,
    *,
    required_execution_profile: str = "common_subset",
    pack_repo: Any = None,
) -> Tuple[Resolution, Dict[str, str]]:
    caps: Dict[str, str] = {}
    arts: Dict[str, str] = {}

    async def pin_cap(ref) -> Optional[str]:
        if ref.ref_id not in caps:
            v = await _pin_capability(cap_repo, ref)
            if v is not None:
                caps[ref.ref_id] = v
        return caps.get(ref.ref_id)

    async def pin_art(ref) -> Optional[str]:
        if ref.ref_id not in arts:
            v = await _pin_artifact(schema_repo, ref)
            if v is not None:
                arts[ref.ref_id] = v
        return arts.get(ref.ref_id)

    for rc in manifest.requires_capabilities:
        await pin_cap(rc.ref)
    for ref in manifest.artifacts:
        await pin_art(ref)

    bindings = []
    for b in manifest.bindings:
        ex = b.executor
        exec_cap = assist = None
        if ex.type == "capability":
            v = await pin_cap(ex.capability)
            exec_cap = f"{ex.capability.ref_id}@{v}" if v else None
        elif ex.type == "human" and ex.assist_capability is not None:
            v = await pin_cap(ex.assist_capability)
            assist = f"{ex.assist_capability.ref_id}@{v}" if v else None
        inputs, outputs = [], []
        for io in b.inputs:
            v = await pin_art(io.schema_)
            inputs.append(ResolvedIO(name=io.name, schema=f"{io.schema_.ref_id}@{v}"))
        for io in b.outputs:
            v = await pin_art(io.schema_)
            outputs.append(ResolvedIO(name=io.name, schema=f"{io.schema_.ref_id}@{v}"))
        bindings.append(ResolvedBinding(
            element_id=b.element_id, executor_capability=exec_cap,
            assist_capability=assist, inputs=inputs, outputs=outputs,
        ))

    # ADR-039: pin each callActivity's callee pack@range → the active exact version, and lift the
    # composite required profile to max(caller, callee…) so the runtime's profile guard still holds.
    call_activities = []
    prof = required_execution_profile
    for b in manifest.bindings:
        if b.executor.type != "call":
            continue
        cpack, cspec = b.executor.pack, b.executor.version
        cver = await _pin_pack(pack_repo, cpack, cspec) if pack_repo is not None else None
        if cver and pack_repo is not None:
            callee_res = await pack_repo.get_resolution(cpack, cver) or {}
            callee_prof = callee_res.get("required_execution_profile", "common_subset")
            if profile_rank(callee_prof) > profile_rank(prof):
                prof = normalize_profile(callee_prof)
        call_activities.append(ResolvedCall(
            element=b.element_id, pack_key=cpack, version=cver or "",
            input_map=dict(b.executor.input_map), output_map=dict(b.executor.output_map)))

    return (
        Resolution(capabilities=caps, artifacts=arts, bindings=bindings,
                   call_activities=call_activities, required_execution_profile=prof),
        dict(caps),
    )
