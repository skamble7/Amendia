# tests/test_deletion.py
"""ADR-061 — clean deletion of a pack version / whole pack: audit-first, ordered, idempotent cascade."""
from app.services.deletion import delete_versions

PK, PV = "wire-repair-standard", "1.0.0"

_ALL_COLLECTIONS = (
    "process_packs", "capabilities", "artifact_schemas", "bpmn_documents",
    "validation_reports", "pack_resolutions", "pack_roles",
)


class RecordingPublisher:
    """Captures published lifecycle events AND, at publish time, snapshots whether the pack manifest still
    exists — so a test can prove the audit event is emitted BEFORE the rows are removed (ADR-061 D3)."""
    is_ready = True

    def __init__(self, db):
        self._db = db
        self.events: list = []
        self.pack_rows_at_emit: list = []

    async def publish(self, doc, routing_key, message_id):
        n = await self._db["process_packs"].count_documents(
            {"pack_key": doc["pack_key"], "version": doc["version"]})
        self.pack_rows_at_emit.append(n)
        self.events.append((routing_key, doc))


class NullPublisher:
    is_ready = False


def _svc_args(pack_repo, bpmn_repo, cap_repo, schema_repo, onboarding_repo, resolver, publisher):
    return dict(pack_repo=pack_repo, bpmn_repo=bpmn_repo, cap_repo=cap_repo, schema_repo=schema_repo,
                onboarding_repo=onboarding_repo, publisher=publisher, resolver=resolver)


async def test_delete_is_audit_first_and_purges_every_collection(
    onboarded, db, pack_repo, bpmn_repo, cap_repo, schema_repo, onboarding_repo, resolver
):
    m = await pack_repo.get(PK, PV)
    assert m is not None
    assert len(await cap_repo.list_owned(PK, PV)) > 0            # seed owns caps/schemas (ADR-060)
    assert len(await schema_repo.list_owned(PK, PV)) > 0

    pub = RecordingPublisher(db)
    summary = await delete_versions(
        pack_key=PK, versions=[m], actor="usr-owner", whole_pack=False,
        **_svc_args(pack_repo, bpmn_repo, cap_repo, schema_repo, onboarding_repo, resolver, pub))

    # AUDIT FIRST: one delete event, and the manifest STILL existed when it was published.
    assert len(pub.events) == 1
    ev = pub.events[0][1]
    assert ev["op"] == "delete" and ev["pack_key"] == PK and ev["version"] == PV
    assert ev["actor"] == "usr-owner" and "status=active" in (ev.get("detail") or "")
    assert pub.pack_rows_at_emit == [1]                          # row present at emit → audit-before-delete

    # ZERO rows remain for the pack in EVERY collection.
    for coll in _ALL_COLLECTIONS:
        assert await db[coll].count_documents({"pack_key": PK}) == 0, coll

    assert summary["deleted_versions"] == [PV]
    assert summary["versions"][0]["purged"]["capabilities"] > 0
    assert summary["versions"][0]["status_at_delete"] == "active"


async def test_delete_cascade_is_idempotent(
    onboarded, pack_repo, bpmn_repo, cap_repo, schema_repo, onboarding_repo, resolver
):
    m = await pack_repo.get(PK, PV)
    args = _svc_args(pack_repo, bpmn_repo, cap_repo, schema_repo, onboarding_repo, resolver, NullPublisher())
    await delete_versions(pack_key=PK, versions=[m], actor="o", whole_pack=False, **args)
    # re-run the cascade on already-deleted rows → all zero counts, no error (safe retry of a partial delete).
    again = await delete_versions(pack_key=PK, versions=[m], actor="o", whole_pack=False, **args)
    purged = again["versions"][0]["purged"]
    assert purged["process_packs"] == 0 and purged["capabilities"] == 0 and purged["artifact_schemas"] == 0


async def test_delete_version_endpoint_purges_and_404s_on_missing(client, onboarded):
    assert (await client.get(f"/packs/{PK}/{PV}")).status_code == 200
    # the pack owns caps via the nested collection route (Phase 4) before delete
    assert len((await client.get(f"/packs/{PK}/{PV}/capabilities")).json()) > 0

    r = await client.delete(f"/packs/{PK}/{PV}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_versions"] == [PV]
    assert body["versions"][0]["purged"]["capabilities"] > 0

    assert (await client.get(f"/packs/{PK}/{PV}")).status_code == 404      # manifest gone
    assert (await client.get(f"/packs/{PK}/{PV}/capabilities")).json() == []  # owned catalog gone
    assert (await client.delete(f"/packs/{PK}/{PV}")).status_code == 404   # re-delete → absent


async def test_delete_whole_pack_endpoint(client, onboarded):
    r = await client.delete(f"/packs/{PK}")
    assert r.status_code == 200
    body = r.json()
    assert body["whole_pack"] is True and PV in body["deleted_versions"]
    assert (await client.get(f"/packs/{PK}")).status_code == 404          # no versions left


async def test_delete_unknown_pack_404(client):
    assert (await client.delete("/packs/does-not-exist/1.0.0")).status_code == 404
    assert (await client.delete("/packs/does-not-exist")).status_code == 404
