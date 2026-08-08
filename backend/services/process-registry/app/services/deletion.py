# app/services/deletion.py
"""ADR-061 — clean deletion of a pack version / whole pack.

The cascade is AUDIT-FIRST and ORDERED (D3/D5): for each target version, emit the ``delete`` lifecycle event
BEFORE removing any row (so the GLEA trail survives a partial failure), then delete ``process_packs`` FIRST
(immediately un-loadable/un-resolvable), then the per-version sidecars, then the pack-OWNED
capabilities/schemas (ADR-060 — a pure cascade, no reference-counting), then the committed onboarding sessions.
Every step is an idempotent ``delete_many`` → a re-run of a partial delete is a clean no-op.
"""
from __future__ import annotations

from typing import Any, Dict, List

from amendia_contracts.process_pack import ProcessPackManifest
from app.events.publisher import emit_pack_lifecycle


async def delete_versions(
    *,
    pack_key: str,
    versions: List[ProcessPackManifest],
    actor: str,
    whole_pack: bool,
    pack_repo: Any,
    bpmn_repo: Any,
    cap_repo: Any,
    schema_repo: Any,
    onboarding_repo: Any,
    publisher: Any,
    resolver: Any,
) -> Dict[str, Any]:
    """Force-delete every ``version`` in ``versions`` (any status) with the ADR-061 audit-first cascade.
    Returns a per-version purge summary. ``resolver.invalidate()`` is called when an active pack was removed
    so it stops resolving immediately (the resolver holds a TTL cache of active packs)."""
    per_version: List[Dict[str, Any]] = []
    had_active = False

    for m in versions:
        version = m.version
        status = m.status.value if hasattr(m.status, "value") else str(m.status)
        had_active = had_active or status == "active"

        # 1) AUDIT FIRST — before any row is removed (survives a partial failure; GLEA is a separate SOR).
        detail = f"force-delete {pack_key}@{version} at status={status}"
        if whole_pack:
            detail += "; whole-pack delete"
        if status == "active":
            detail += "; WARNING: active pack — in-flight instances may strand if they resume against the removed bundle"
        await emit_pack_lifecycle(publisher, pack_key=pack_key, version=version, op="delete",
                                  actor=actor, detail=detail)

        # 2) process_packs FIRST (+ the sidecars this repo owns) → pack is un-loadable/un-resolvable.
        pack_counts = await pack_repo.delete_version(pack_key, version)
        # 3) remaining per-version sidecar, 4) pack-owned catalog, 5) authoring scratch.
        bpmn_n = await bpmn_repo.delete(pack_key, version)
        caps_n = await cap_repo.delete_owned(pack_key, version)
        schemas_n = await schema_repo.delete_owned(pack_key, version)
        sessions_n = await onboarding_repo.delete_for_pack(pack_key, version)

        per_version.append({
            "version": version,
            "status_at_delete": status,
            "purged": {
                **pack_counts,  # process_packs, validation_reports, pack_resolutions, pack_roles
                "bpmn_documents": bpmn_n,
                "capabilities": caps_n,
                "artifact_schemas": schemas_n,
                "onboarding_sessions": sessions_n,
            },
        })

    # Whole-pack: a final pack_key-scoped sweep catches any straggler (e.g. a session for a version that was
    # not in list_versions) so ZERO rows remain for the pack_key. Idempotent.
    if whole_pack:
        await pack_repo.delete_pack(pack_key)
        await bpmn_repo.delete_pack(pack_key)
        await onboarding_repo.delete_for_pack(pack_key)

    if had_active:
        resolver.invalidate()

    return {
        "pack_key": pack_key,
        "whole_pack": whole_pack,
        "deleted_versions": [v["version"] for v in per_version],
        "versions": per_version,
    }
