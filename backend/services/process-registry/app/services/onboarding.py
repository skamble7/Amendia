# app/services/onboarding.py
"""The OnboardingSession state machine.

One method per transition; each guards ordering, applies the invalidation cascade when an
upstream step is re-edited, and returns the full updated session (the webui renders it).
Nothing touches the shared catalog collections until :meth:`commit`, which runs the same
ordered, idempotent chain the seeder uses (artifacts → capabilities → pack draft → BPMN →
validate → activate) — reusing ``register_schema`` / ``resolve_pins`` / ``PackValidator``
rather than re-implementing them.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from packaging.version import Version
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from amendia_bpmn import (
    TASK_EXECUTOR_CATEGORY,
    extract_semantics,
    parse as parse_bpmn,
    parse_decision_table,
    parse_reduce_config,
    required_profile,
    select_process_id,
    validate_reduce,
    validate_table,
)

from app.services.inference import (
    build_semantic_summary,
    infer_draft,
    refine_input_sources,
    suggest_binding_input_map,
)

from amendia_contracts.artifact_schema import ArtifactSchemaRegistration
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.common import PACK_KEY_RE, SEMVER_RE, HitlMode, hitl_mode_at_least
from amendia_contracts.process_pack import ProcessPackManifest, TriageRule

from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.base import DuplicateError
from app.dal.bpmn_repo import BpmnRepository
from app.dal.capability_repo import CapabilityRepository
from app.dal.onboarding_repo import OnboardingRepository
from app.dal.pack_repo import ProcessPackRepository
from app.models.onboarding import (
    AttachBpmnRequest,
    Basics,
    BindingInput,
    BpmnInventory,
    CommitStep,
    CreateSessionRequest,
    IntrospectMcpRequest,
    IntrospectMcpResponse,
    OnboardingSession,
    OnboardingState,
    SetBindingsRequest,
    SetCapabilitiesRequest,
    SetPoliciesRequest,
    DeclareArtifactRequest,
    RefineArtifactRequest,
    DeclareTriggerRequest,
    SetTriageRequest,
    RoleMeta,
    StagedArtifact,
    StagedBinding,
    StagedBindingIO,
    StagedCapability,
    StagedGatewayVariable,
    StagedSod,
    StagedTriageRule,
    state_rank,
)
from app.services.activation import resolve_pins
from app.services.mcp_introspect import (
    McpConnectionError,
    McpIntrospector,
    classify_id_collision,
    infer_capability,
    introspect_response_tool,
    normalize_artifact_schema,
    sanitize_name as _san,
)
from app.services.registration import RegistrationError, register_schema
from app.validation.bpmn import compute_sha256
from app.validation.pack_validator import PackValidator
from app.validation.predicates import (
    PredicateSyntaxError,
    check_predicate,
    flatten_schema_fields,
    infer_field_types,
    validate_predicate,
)

_DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")
# ADR-049: a declared trigger artifact id — art.<domain>.<name> (dots inside <name> allowed).
_ART_ID_RE = re.compile(r"^art\.[a-z0-9_]+\.[a-z0-9_.]+$")
_APPROVE_ACTIONS = HitlMode.APPROVE_ACTIONS

# ADR-046 (Track 2): field types for the inferred verdict/summary artifact.
_DMN_TYPE_JSON = {"number": "number", "integer": "integer", "boolean": "boolean", "string": "string"}
_REDUCE_OP_TYPE = {
    "any": "boolean", "all": "boolean", "none": "boolean", "count": "integer",
    "sum": "number", "avg": "number", "min": "number", "max": "number",
    "first": "string", "last": "string",
}


def _is_loopback_endpoint(endpoint: str) -> bool:
    """True if the URL's host is a loopback the registry container can't use to reach the operator's
    host (``localhost``/``127.x``/``::1``/``0.0.0.0``) — used to add a clearer introspection hint."""
    try:
        host = (urlsplit(endpoint).hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "0.0.0.0", "::1") or host.startswith("127.")


def humanize_role(role_id: str) -> str:
    """Fallback label for a role id with no authored metadata: last dotted segment,
    Title Cased (``role.payments.ops_analyst`` → ``Ops Analyst``)."""
    tail = role_id.rsplit(".", 1)[-1]
    return tail.replace("_", " ").title() or role_id


# -- ADR-056 reverse-hydration helpers (manifest → session) -- #
def _enum(v: Any) -> Any:
    """The plain value of a possibly-enum field (``kind``/``side_effect``/``compatibility``…)."""
    return getattr(v, "value", v)


def _ref_parts(ref: str) -> Tuple[str, str]:
    """Split a versioned ref (``art.x@^1.2.3`` / ``cap.x@1.2.3``) → (id, exact version). Range operators stripped;
    an id with no ``@`` defaults to 1.0.0."""
    core = (ref or "").split("@", 1)
    key = core[0]
    ver = core[1].lstrip("^~>=< ") if len(core) == 2 and core[1] else "1.0.0"
    return key, (ver or "1.0.0")


def _domain_from_pack(raw: Dict[str, Any]) -> str:
    """Derive the pack's default domain from a ``cap.<domain>.<tool>`` (else ``art.<domain>.<name>``) ref."""
    for rc in raw.get("requires_capabilities", []):
        ref = rc.get("resolved") or rc.get("ref") or ""
        parts = _ref_parts(ref)[0].split(".")
        if len(parts) >= 3 and parts[0] == "cap":
            return parts[1]
    for a in raw.get("artifacts", []):
        parts = _ref_parts(a)[0].split(".")
        if len(parts) >= 3 and parts[0] == "art":
            return parts[1]
    return _san(raw.get("pack_key", ""))


class TransitionError(Exception):
    """A guard/validation failure → mapped to ``HTTPException(status_code, detail)``."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


# --------------------------------------------------------------------------- #
# Dry-run overlays: make staged (unregistered) rows visible to the real validator.
# --------------------------------------------------------------------------- #

class _CapOverlay:
    def __init__(self, real: CapabilityRepository, staged: List[CapabilityDescriptor]) -> None:
        self._real = real
        self._staged = staged

    async def list_by_id(self, capability_id: str) -> List[CapabilityDescriptor]:
        base = await self._real.list_by_id(capability_id)
        return base + [c for c in self._staged if c.capability_id == capability_id]


class _SchemaOverlay:
    def __init__(self, real: ArtifactSchemaRepository, staged: List[ArtifactSchemaRegistration]) -> None:
        self._real = real
        self._staged = staged

    async def list_by_key(self, artifact_key: str) -> List[ArtifactSchemaRegistration]:
        base = await self._real.list_by_key(artifact_key)
        return base + [s for s in self._staged if s.artifact_key == artifact_key]


class OnboardingService:
    def __init__(
        self,
        onboarding_repo: OnboardingRepository,
        cap_repo: CapabilityRepository,
        schema_repo: ArtifactSchemaRepository,
        pack_repo: ProcessPackRepository,
        bpmn_repo: BpmnRepository,
        introspector: McpIntrospector,
        sample_envelopes: Optional[List[dict]] = None,
        profile: str = "common_subset",
    ) -> None:
        self.sessions = onboarding_repo
        self.caps = cap_repo
        self.schemas = schema_repo
        self.profile = profile  # ADR-027 Phase 2: which BPMN constructs may activate
        self.packs = pack_repo
        self.bpmn = bpmn_repo
        self.introspector = introspector
        self._samples = sample_envelopes or []

    # ------------------------------------------------------------------ #
    # Read / list / delete
    # ------------------------------------------------------------------ #
    async def get(self, session_id: str, *, owner: str) -> OnboardingSession:
        s = await self.sessions.get(session_id)
        if s is None:
            raise TransitionError(404, f"unknown onboarding session '{session_id}'")
        if s.created_by != owner:
            raise TransitionError(404, f"unknown onboarding session '{session_id}'")
        return s

    async def list(self, *, owner: str) -> List[OnboardingSession]:
        return await self.sessions.list_for(owner)

    async def delete(self, session_id: str, *, owner: str) -> None:
        s = await self.get(session_id, owner=owner)  # ownership + existence
        await self.sessions.delete(s.session_id)

    # ------------------------------------------------------------------ #
    # MCP introspection (no session mutation)
    # ------------------------------------------------------------------ #
    async def introspect_mcp(self, req: IntrospectMcpRequest) -> IntrospectMcpResponse:
        # Operator-supplied URL → SSRF surface. Owner-gating + timeout live elsewhere; here
        # we refuse anything but http(s) (deployments may layer a stricter egress allowlist).
        if not re.match(r"^https?://", req.endpoint, re.IGNORECASE):
            raise TransitionError(400, {"error": "invalid_endpoint",
                                        "message": "endpoint must be an http(s) URL"})
        # L1: the domain seeds the suggested capability ids in the preview — no business-area default.
        if not (req.domain and _DOMAIN_RE.match(req.domain)):
            raise TransitionError(422, {"error": "invalid_domain",
                                        "message": "a valid domain ([a-z0-9_]+) is required to introspect"})
        domain = req.domain
        try:
            tools = await self.introspector.list_tools(
                endpoint=req.endpoint, transport=req.transport, headers=req.headers
            )
        except McpConnectionError as exc:
            message = str(exc)
            # The registry usually runs inside a container, where a loopback host is the container
            # itself — not the operator's laptop (that URL works for MCP Inspector, not for us). If the
            # connection to a loopback endpoint failed, add the deployment-facing-URL hint (ADR-024 §5).
            if _is_loopback_endpoint(req.endpoint):
                message += (" — the registry connects from inside its container, so 'localhost' reaches "
                            "the container itself, not your host. Use the deployment-facing URL (e.g. the "
                            "Docker service alias like http://<service>:<port>/mcp), not localhost.")
            raise TransitionError(502, {"error": "mcp_connection_failed", "message": message})
        # Batch-4: for each compliant tool, classify its derived cap.<domain>.<tool> id against the ACTIVE
        # catalog — a hard collision (contract differs) or a benign reuse opportunity. Advisory (non-blocking);
        # the wizard surfaces the diff + a "distinct domain" / "reuse" fix at the Capabilities step, so the
        # cap.<domain>.* clash that later becomes binding_io_mismatch is caught here, not at assemble.
        resp_tools = [introspect_response_tool(t, domain=domain) for t in tools]
        for rt in resp_tools:
            if rt.compliance.compliant and rt.suggested_capability_id:
                active = [v for v in await self.caps.list_by_id(rt.suggested_capability_id)
                          if v.status.value == "active"]
                rt.id_collision = classify_id_collision(active, domain=domain, tool=rt.name)
        return IntrospectMcpResponse(endpoint=req.endpoint, transport=req.transport, tools=resp_tools)

    # ------------------------------------------------------------------ #
    # 1) create — INITIATED
    # ------------------------------------------------------------------ #
    async def create(self, req: CreateSessionRequest, *, owner: str) -> OnboardingSession:
        errors: List[dict] = []
        if not re.match(PACK_KEY_RE, req.pack_key):
            errors.append({"field": "pack_key", "message": "must be kebab-case (lowercase, hyphen-separated)"})
        if not re.match(SEMVER_RE, req.version):
            errors.append({"field": "version", "message": "must be semver (major.minor.patch)"})
        if not req.title.strip():
            errors.append({"field": "title", "message": "title is required"})
        # L1: no hardcoded business domain. Operator-supplied; else derive deterministically from the
        # pack_key (sanitized) so ids are process-scoped and don't collide with the active catalog.
        domain = (req.default_domain or "").strip() or _san(req.pack_key)
        if not _DOMAIN_RE.match(domain):
            errors.append({"field": "default_domain",
                           "message": "domain must match [a-z0-9_]+ (or omit it to derive from pack_key)"})
        if errors:
            raise TransitionError(422, {"errors": errors})

        existing = await self.packs.get(req.pack_key, req.version)
        if existing is not None and existing.status.value in ("active", "deprecated"):
            raise TransitionError(409, {"errors": [{
                "field": "version",
                "message": f"{req.pack_key}@{req.version} already exists as an {existing.status.value} "
                           f"pack; bump the version to onboard a revision",
            }]})

        session = OnboardingSession(
            session_id="onb-" + uuid.uuid4().hex[:12],
            created_by=owner,
            state=OnboardingState.INITIATED,
            basics=Basics(
                pack_key=req.pack_key, version=req.version, title=req.title,
                description=req.description, default_domain=domain,
            ),
            # Batch-4: the trigger field/type map (from the deployment sample envelopes) so the Triage step can
            # author against the real schema — a field picker + type-valid ops. Empty ⇒ free-text fallback.
            trigger_fields=infer_field_types(self._samples),
        )
        return await self.sessions.insert(session)

    # ------------------------------------------------------------------ #
    # ADR-056: edit an activated pack's CONFIG by cloning it into a new version — hydrate an OnboardingSession
    # from the stored pack (the inverse of _compose), bump the version, and hand it to the stepped review.
    # ------------------------------------------------------------------ #
    async def create_edit_session(self, pack_key: str, *, bump: str = "minor", owner: str) -> OnboardingSession:
        """Open an edit session over the current active (else highest) version of ``pack_key`` at a bumped version."""
        versions = await self.packs.list_versions(pack_key)
        if not versions:
            raise TransitionError(404, {"error": "pack_not_found",
                                        "message": f"no pack '{pack_key}' to edit"})
        active = [m for m in versions if m.status.value == "active"]
        base = active[0] if active else max(versions, key=lambda m: Version(m.version))
        new_version = self._next_pack_version([m.version for m in versions], bump)
        return await self.hydrate_from_pack(pack_key, base.version, new_version, owner=owner)

    @staticmethod
    def _next_pack_version(versions: List[str], bump: str) -> str:
        highest = max(Version(v) for v in versions)
        nv = f"{highest.major + 1}.0.0" if bump == "major" else f"{highest.major}.{highest.minor + 1}.0"
        if nv in {str(Version(v)) for v in versions}:                # defensive — bumping the highest can't collide
            raise TransitionError(409, {"error": "version_collision", "message": f"version {nv} already exists"})
        return nv

    async def hydrate_from_pack(self, pack_key: str, source_version: str, new_version: str,
                                *, owner: str) -> OnboardingSession:
        """Build an ASSEMBLED OnboardingSession from a STORED, activated pack — the inverse of ``_compose``. Reads
        the pack + its sidecars (never the original onboarding session), rebuilds staged caps/schemas from the
        registry (no MCP re-introspect), re-parses the SAME BPMN + re-runs inference, then reuses ``assemble`` to
        re-validate. The new pack carries the SAME BPMN (content + sha) forward to ``new_version`` at commit."""
        raw = await self.packs.get_raw(pack_key, source_version)
        if raw is None:
            raise TransitionError(404, {"error": "pack_not_found",
                                        "message": f"{pack_key}@{source_version} not found"})
        if await self.packs.get(pack_key, new_version) is not None:
            raise TransitionError(409, {"error": "version_collision",
                                        "message": f"{pack_key}@{new_version} already exists"})
        bpmn_xml = await self.bpmn.get_xml(pack_key, source_version)
        if not bpmn_xml or not bpmn_xml.strip():
            raise TransitionError(422, {"error": "bpmn_missing",
                                        "message": f"{pack_key}@{source_version} has no stored BPMN"})

        session_id = "onb-" + uuid.uuid4().hex[:12]
        domain = _domain_from_pack(raw)

        # capabilities + their I/O schemas ← requires_capabilities (rebuilt from the registered descriptors)
        staged_caps: List[StagedCapability] = []
        staged_arts: Dict[str, StagedArtifact] = {}
        reused_refs: List[str] = []
        for rc in raw.get("requires_capabilities", []):
            resolved = rc.get("resolved") or rc.get("ref") or ""
            cap_id, cap_ver = _ref_parts(resolved)
            desc = await self.caps.get(cap_id, cap_ver)
            if desc is None:
                if rc.get("ref"):
                    reused_refs.append(rc["ref"])                    # can't rebuild → carry as a reused ref
                continue
            sc = self._staged_capability_from_descriptor(desc)
            staged_caps.append(sc)
            for key in (sc.input_artifact_key, sc.output_artifact_key):
                if key and key not in staged_arts:
                    art = await self._staged_artifact_from_key(key)
                    if art is not None:
                        staged_arts[key] = art

        # human-authored artifacts ← the schema_refs on human bindings' outputs (so the refiner can edit them)
        authored: Dict[str, StagedArtifact] = {}
        for b in raw.get("bindings", []):
            if (b.get("executor") or {}).get("type") == "human":
                for io in b.get("outputs", []):
                    key, _v = _ref_parts(io.get("schema", ""))
                    if key and key not in authored and key not in staged_arts:
                        art = await self._staged_artifact_from_key(key)
                        if art is not None:
                            authored[key] = art

        trigger_artifact = None
        if raw.get("trigger"):
            trigger_artifact = await self._staged_artifact_from_key(_ref_parts(raw["trigger"])[0])

        bindings = [self._staged_binding_from_manifest(b) for b in raw.get("bindings", [])]
        triage = [StagedTriageRule(rule_id=r["rule_id"], priority=r.get("priority", 100),
                                   description=r.get("description"), when=r.get("when", {}))
                  for r in raw.get("triage_rules", [])]
        gvars = [StagedGatewayVariable(gateway_id=g["gateway_id"], variable=g["variable"],
                                       source_artifact=g["source_artifact"])
                 for g in (raw.get("gateway_variables") or [])]
        sod = [StagedSod(elements=s.get("elements", []))
               for s in ((raw.get("policies") or {}).get("separation_of_duties") or [])]
        role_docs = await self.packs.get_pack_roles(pack_key, source_version)
        roles = [d["role_id"] for d in role_docs]
        role_meta = {d["role_id"]: RoleMeta(label=d.get("label"), description=d.get("description")) for d in role_docs}
        if not roles:                                                # sidecar absent → derive from the bindings
            roles = sorted({r for b in bindings for r in (b.role, b.hitl_role) if r})

        # BPMN inventory + inference re-derived from the SAME xml (read-only Understanding/Gateways views)
        process_id, inv_errors, inventory = self._parse_and_check_bpmn(bpmn_xml)
        if inv_errors:
            raise TransitionError(422, {"error": "bpmn_invalid", "findings": inv_errors})
        sem = extract_semantics(bpmn_xml, process_id)
        sha = ((raw.get("process") or {}).get("bpmn_sha256")) or compute_sha256(bpmn_xml)
        bpmn = BpmnInventory(
            process_id=process_id, bpmn_file=(raw.get("process") or {}).get("bpmn_file") or f"{pack_key}.bpmn",
            sha256=sha, bindable_elements=inventory["bindable_elements"],
            service_tasks=inventory["service_tasks"], user_tasks=inventory["user_tasks"],
            gateways=inventory["gateways"], task_names=inventory["task_names"],
            subprocesses=inventory.get("subprocesses", []),
            documented_elements=inventory.get("documented_elements", []),
            coverage_counts=inventory.get("coverage_counts", {}),
            required_execution_profile=inventory.get("required_execution_profile", "common_subset"),
            **build_semantic_summary(sem))

        session = OnboardingSession(
            session_id=session_id, created_by=owner, state=OnboardingState.POLICIES_SET,
            basics=Basics(pack_key=pack_key, version=new_version, title=raw.get("title") or pack_key,
                          description=raw.get("description"), default_domain=domain),
            trigger_fields=infer_field_types(self._samples), trigger_artifact=trigger_artifact,
            authored_artifacts=list(authored.values()), bpmn=bpmn,
            staged_artifacts=list(staged_arts.values()), staged_capabilities=staged_caps,
            reused_capability_refs=reused_refs, bindings=bindings, triage_rules=triage,
            gateway_variables=gvars, sod_policies=sod, roles=roles, role_meta=role_meta,
            inferred=infer_draft(sem, domain))
        # stage the (unchanged) BPMN under this session's key so commit re-uploads it to the new version
        await self.bpmn.upsert(self._staging_pk(session), new_version, xml=bpmn_xml, sha256=sha)
        await self.sessions.insert(session)
        # reuse assemble to re-validate + advance to ASSEMBLED (so the Review step shows a fresh dry-run)
        return await self.assemble(session_id, owner=owner)

    def _staged_binding_from_manifest(self, b: Dict[str, Any]) -> StagedBinding:
        ex = b.get("executor") or {}
        sb = StagedBinding(element_id=b["element_id"], element_kind=b["element_kind"], executor_type=ex.get("type", ""))
        if ex.get("type") == "capability":
            sb.capability_ref = ex.get("capability")
        elif ex.get("type") == "human":
            sb.role = ex.get("role")
            sb.assist_capability_ref = ex.get("assist_capability")
        elif ex.get("type") == "message":
            sb.message_name = ex.get("message_name")
        elif ex.get("type") == "call":
            sb.call_pack = ex.get("pack")
            sb.call_version = ex.get("version")
            sb.input_map = dict(ex.get("input_map") or {})
            sb.output_map = dict(ex.get("output_map") or {})
        hitl = b.get("hitl") or {}
        sb.hitl_mode = hitl.get("mode", "none")
        sb.hitl_role = hitl.get("role")
        sb.inputs = [StagedBindingIO(name=io["name"], schema_ref=io["schema"], required=io.get("required", True))
                     for io in b.get("inputs", [])]
        sb.outputs = [StagedBindingIO(name=io["name"], schema_ref=io["schema"], required=io.get("required", True))
                      for io in b.get("outputs", [])]
        sb.input_sources = dict(b.get("input_map") or {})           # ADR-048 per-input sources (not the call maps)
        return sb

    def _staged_capability_from_descriptor(self, desc: Any) -> StagedCapability:
        in_io = desc.inputs[0] if desc.inputs else None
        out_io = desc.outputs[0] if desc.outputs else None
        kind = _enum(desc.kind)
        sc = StagedCapability(
            capability_id=desc.capability_id, version=desc.version, title=desc.title, description=desc.description,
            kind=kind, side_effect=_enum(desc.side_effect), idempotent=desc.idempotent,
            min_hitl_mode=(_enum(desc.constraints.min_hitl_mode)
                           if desc.constraints and desc.constraints.min_hitl_mode else None),
            input_name=(in_io.name if in_io else "in"),
            input_artifact_key=(_ref_parts(str(in_io.schema_))[0] if in_io else ""),
            output_name=(out_io.name if out_io else "out"),
            output_artifact_key=(_ref_parts(str(out_io.schema_))[0] if out_io else ""))
        rt = desc.runtime
        if kind == "mcp":
            sc.endpoint = getattr(rt, "endpoint", None)
            tools = getattr(rt, "tools", None) or []
            sc.tool = tools[0] if tools else None
            sc.transport = getattr(rt, "transport", None) or "streamable_http"
            sc.headers = dict(getattr(rt, "headers", None) or {})
        elif kind == "decision":
            sc.table = getattr(rt, "table", None)
        elif kind == "reduce":
            sc.config = getattr(rt, "config", None)
        return sc

    async def _staged_artifact_from_key(self, key: str) -> Optional[StagedArtifact]:
        if not key:
            return None
        regs = await self.schemas.list_by_key(key)
        if not regs:
            return None
        reg = max(regs, key=lambda r: Version(r.version))           # the highest registered version at this key
        return StagedArtifact(artifact_key=key, version=reg.version, title=reg.title,
                              description=reg.description, json_schema=reg.json_schema,
                              compatibility=_enum(getattr(reg, "compatibility", "backward")))

    # ------------------------------------------------------------------ #
    # 2) attach_bpmn — BPMN_ATTACHED
    # ------------------------------------------------------------------ #
    async def attach_bpmn(self, session_id: str, req: AttachBpmnRequest, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        xml = req.bpmn_xml
        if not xml or not xml.strip():
            raise TransitionError(422, {"errors": [{"field": "bpmn_xml", "message": "empty BPMN body"}]})

        process_id, inv_errors, inventory = self._parse_and_check_bpmn(xml)
        if inv_errors:
            raise TransitionError(422, {"error": "bpmn_invalid", "findings": inv_errors})

        sha = compute_sha256(xml)
        bpmn_file = req.bpmn_file or f"{s.basics.pack_key}.bpmn"
        # Persist the XML on the session's staging key so commit can re-upload it.
        await self.bpmn.upsert(self._staging_pk(s), s.basics.version, xml=xml, sha256=sha)
        # Phase 1: read the whole diagram (semantics) and derive the advisory inference draft.
        sem = extract_semantics(xml, process_id)
        s.bpmn = BpmnInventory(
            process_id=process_id, bpmn_file=bpmn_file, sha256=sha,
            bindable_elements=inventory["bindable_elements"],
            service_tasks=inventory["service_tasks"], user_tasks=inventory["user_tasks"],
            gateways=inventory["gateways"], task_names=inventory["task_names"],
            subprocesses=inventory.get("subprocesses", []),
            documented_elements=inventory.get("documented_elements", []),
            coverage_counts=inventory.get("coverage_counts", {}),
            required_execution_profile=inventory.get("required_execution_profile", "common_subset"),
            **build_semantic_summary(sem),
        )
        s.inferred = infer_draft(sem, s.basics.default_domain)
        # Re-attaching BPMN re-derives inventory and invalidates everything that referenced
        # task/gateway ids (bindings, gateway variables, SoD) plus the dry-run.
        cleared = self._clear(s, {"bindings", "gateway_variables", "sod_policies", "dry_run"})
        s.state = OnboardingState.CAPABILITIES_RESOLVED if s.staged_capabilities or s.reused_capability_refs \
            else OnboardingState.BPMN_ATTACHED
        s.last_cleared = cleared
        return await self.sessions.save(s)

    # ------------------------------------------------------------------ #
    # 3) set_capabilities — CAPABILITIES_RESOLVED
    # ------------------------------------------------------------------ #
    async def set_capabilities(self, session_id: str, req: SetCapabilitiesRequest, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        if s.bpmn is None:
            raise TransitionError(409, "attach a BPMN before staging capabilities")

        staged_arts: List[StagedArtifact] = []
        staged_caps: List[StagedCapability] = []
        errors: List[dict] = []

        for sel in req.tools:
            domain = sel.domain or s.basics.default_domain
            ids = {
                "input_artifact_key": sel.input_artifact_key or f"art.{domain}.{_san(sel.tool)}_input",
                "output_artifact_key": sel.output_artifact_key or f"art.{domain}.{_san(sel.tool)}_output",
                "capability_id": sel.capability_id or f"cap.{domain}.{_san(sel.tool)}",
            }
            try:
                in_art, out_art, cap, _warn = infer_capability(
                    tool=sel.tool, endpoint=sel.endpoint, transport=sel.transport, headers=sel.headers,
                    domain=domain, input_schema=sel.input_schema, output_schema=sel.output_schema,
                    input_artifact_key=ids["input_artifact_key"], output_artifact_key=ids["output_artifact_key"],
                    capability_id=ids["capability_id"], artifact_version=sel.artifact_version,
                    capability_version=sel.capability_version, side_effect=sel.side_effect,
                    idempotent=sel.idempotent, min_hitl_mode=sel.min_hitl_mode,
                    title=sel.title, description=sel.description,
                )
            except ValueError as exc:
                errors.append({"tool": sel.tool, "message": str(exc)})
                continue
            staged_arts.extend([in_art, out_art])
            staged_caps.append(cap)

        # ADR-046 (Track 2): inline-authored decision / reduce capabilities. Each is structurally
        # validated by the shared amendia_bpmn checks (surfacing dmn_*/reduce_* as field errors) and
        # stages its own inferred verdict/summary output artifact — mirroring the MCP path.
        for spec in req.decision_specs:
            art, cap = self._stage_decision(spec, s, errors)
            if art is not None and cap is not None:
                staged_arts.append(art)
                staged_caps.append(cap)
        for spec in req.reduce_specs:
            art, cap = self._stage_reduce(spec, s, errors)
            if art is not None and cap is not None:
                staged_arts.append(art)
                staged_caps.append(cap)

        # Reused capabilities must exist and be active *now* (re-checked again at commit).
        reused: List[str] = []
        for ref in req.reused_capability_refs:
            ok, msg = await self._reused_ref_ok(ref)
            if not ok:
                errors.append({"ref": ref, "message": msg})
            else:
                reused.append(ref)

        # Batch-4: the capability-id collision guardrail is now an ADVISORY surfaced at introspect
        # (``id_collision`` per tool), not a hard block here — the operator chooses distinct-domain vs reuse.
        # A hard collision they ignore still fails the assemble dry-run (binding_io_mismatch) as a backstop.
        if errors:
            raise TransitionError(422, {"error": "capabilities_invalid", "errors": errors})

        s.staged_artifacts = staged_arts
        s.staged_capabilities = staged_caps
        s.reused_capability_refs = reused
        # ADR-048 D4: now that the tool schemas exist, upgrade the inferred input-source hints into a
        # field-level input_map (entry→trigger; downstream input fields ← upstream output fields / trigger
        # paths) so the Bindings step pre-fills real data-flow the operator only confirms. Trigger is opaque
        # today (no declared trigger artifact — ADR-047 deferred), so unmatched fields default to a trigger
        # path (the only remaining origin; validated as satisfiable).
        if s.inferred is not None:
            # ADR-052: name-match against the DECLARED trigger's fields when one is declared (mirrors the
            # authoritative set_bindings refine); opaque otherwise. NOT the deployment sample-derived fields.
            refine_input_sources(
                s.inferred, staged_caps, staged_arts,
                trigger_fields=({k.split(".", 1)[0] for k in s.trigger_fields} if s.trigger_artifact else None))
        # Editing capabilities invalidates bindings + gateway variables (source artifacts may
        # have changed) + the dry-run. Triage/SoD/roles are independent and kept.
        cleared = self._clear(s, {"bindings", "gateway_variables", "dry_run"})
        s.state = OnboardingState.CAPABILITIES_RESOLVED
        s.last_cleared = cleared
        return await self.sessions.save(s)

    # ------------------------------------------------------------------ #
    # 4) set_bindings — BINDINGS_SET (bijection + side-effect→HITL guards)
    # ------------------------------------------------------------------ #
    async def set_bindings(self, session_id: str, req: SetBindingsRequest, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        if s.bpmn is None:
            raise TransitionError(409, "attach a BPMN before setting bindings")
        if not (s.staged_capabilities or s.reused_capability_refs):
            raise TransitionError(409, "stage capabilities before setting bindings")

        # ADR-044 (Track 1): the bijection now spans the FULL bindable set (task kinds + message
        # elements + callActivity + isForCompensation handlers); the subProcess / event-subprocess
        # CONTAINERS are excluded (never in bindable_elements). Executor type is validated against each
        # element's category (mirrors the contract's Binding._executor_matches_kind).
        inv_by_id = {e.element_id: e for e in s.bpmn.bindable_elements}
        _category_executor = {"capability": "capability", "human": "human",
                              "message": "message", "call": "call"}
        errors: List[dict] = []
        bound_ids: List[str] = []
        staged: List[StagedBinding] = []
        # ADR-050: the set of artifact keys a human/message binding output may reference — every staged
        # (tool-inferred), authored, and the declared trigger artifact.
        staged_keys = self._staged_artifact_keys(s)
        # ADR-051: the inferred output-name default per capability element (the gateway-condition first segment
        # it feeds, if any) — applied when the operator didn't set an explicit output_name.
        sugg_out = {ib.element_id: ib.suggested_output_name for ib in (s.inferred.bindings if s.inferred else [])}

        for b in req.bindings:
            bound_ids.append(b.element_id)
            inv = inv_by_id.get(b.element_id)
            if inv is None:
                errors.append({"element_id": b.element_id, "field": "element_id",
                               "message": "not a bindable BPMN element (subProcess / event-subprocess "
                                          "containers are structural and never bound)"})
                continue
            if b.element_kind != inv.element_kind:
                errors.append({"element_id": b.element_id, "field": "element_kind",
                               "message": f"element_kind '{b.element_kind}' != BPMN kind '{inv.element_kind}'"})
            expected = _category_executor[inv.category]
            if b.executor_type != expected:
                errors.append({"element_id": b.element_id, "field": "executor",
                               "message": f"{inv.element_kind} must bind a {expected} executor"})
            # HITL applies to capability/human only; a message/call executor has no gate of its own.
            if inv.category in ("message", "call"):
                if b.hitl_mode not in ("none", "", None) or b.hitl_role:
                    errors.append({"element_id": b.element_id, "field": "hitl_mode",
                                   "message": f"a {inv.category} executor has no HITL gate"})
            elif b.hitl_mode != "none" and not b.hitl_role:
                errors.append({"element_id": b.element_id, "field": "hitl_role",
                               "message": f"HITL mode '{b.hitl_mode}' requires a role"})

            io_inputs: List[StagedBindingIO] = []
            io_outputs: List[StagedBindingIO] = []
            message_name: Optional[str] = None
            call_pack: Optional[str] = None
            call_version: Optional[str] = None
            input_map: Dict[str, str] = {}
            output_map: Dict[str, str] = {}
            if b.executor_type == "capability":
                # A capability executor MUST name a capability — a task left "Select…" (e.g. an
                # un-authored decision) is a field error here, not a raw 500 at manifest validation.
                if not b.capability_ref:
                    errors.append({"element_id": b.element_id, "field": "capability_ref",
                                   "message": "capability executor requires a capability (none selected)"})
                else:
                    cap_io = await self._capability_io_and_policy(b.capability_ref, s)
                    if cap_io is None:
                        errors.append({"element_id": b.element_id, "field": "capability_ref",
                                       "message": f"capability '{b.capability_ref}' is not staged or active"})
                    else:
                        side_effect, floor, io_inputs, io_outputs = cap_io
                        self._check_hitl_guard(b, side_effect, floor, errors)
                        # ADR-051: rename the mirrored output so a fed gateway can branch on it. Precedence:
                        # operator-set output_name → inferred gateway default → the capability's <tool>_output.
                        # The artifact schema_ref is unchanged (only the addressable output NAME changes).
                        chosen = (b.output_name or "").strip() or sugg_out.get(b.element_id)
                        if chosen and io_outputs:
                            io_outputs = [StagedBindingIO(name=chosen, schema_ref=io_outputs[0].schema_ref,
                                                          required=io_outputs[0].required)]
            elif b.executor_type == "human":
                if not b.role:
                    errors.append({"element_id": b.element_id, "field": "role",
                                   "message": "human executor requires a role"})
                # ADR-050: a human task may declare the artifact(s) it produces (and reads). Each schema_ref
                # must resolve to a staged/authored/trigger artifact; output names are checked for run-wide
                # uniqueness after the loop (so a from-artifact source can address them unambiguously).
                io_inputs = self._validate_binding_io(b, b.inputs, staged_keys, "inputs", errors)
                io_outputs = self._validate_binding_io(b, b.outputs, staged_keys, "outputs", errors)
            elif b.executor_type == "message":
                # ADR-031: the message this element awaits (advisory BPMN name pre-fills; operator confirms).
                message_name = b.message_name or inv.message_name
                if not message_name:
                    errors.append({"element_id": b.element_id, "field": "message_name",
                                   "message": "message executor requires a message_name"})
                # ADR-050: a message/receive task may likewise declare the artifact(s) it produces.
                io_inputs = self._validate_binding_io(b, b.inputs, staged_keys, "inputs", errors)
                io_outputs = self._validate_binding_io(b, b.outputs, staged_keys, "outputs", errors)
            elif b.executor_type == "call":
                # ADR-039: the callee pack + range + IO maps. Callee existence / IO reconciliation is a
                # cross-pack check run by the assemble dry-run (the call-validation stage), not here.
                call_pack = b.call_pack or inv.called_pack
                call_version = b.call_version or inv.called_version or "^1.0.0"
                input_map = dict(b.input_map)
                output_map = dict(b.output_map)
                if not call_pack:
                    errors.append({"element_id": b.element_id, "field": "call_pack",
                                   "message": "call executor requires a callee pack (calledElement)"})
            staged.append(StagedBinding(
                element_id=b.element_id, element_kind=b.element_kind, executor_type=b.executor_type,
                capability_ref=b.capability_ref, role=b.role, assist_capability_ref=b.assist_capability_ref,
                hitl_mode=b.hitl_mode, hitl_role=b.hitl_role,
                message_name=message_name, call_pack=call_pack, call_version=call_version,
                input_map=input_map, output_map=output_map, input_sources=dict(b.input_sources),
                inputs=io_inputs, outputs=io_outputs,
            ))

        # Bijection: exactly one binding per bindable element, no orphans, no unbound elements.
        seen = set()
        for eid in bound_ids:
            if eid in seen:
                errors.append({"element_id": eid, "field": "element_id", "message": "duplicate binding"})
            seen.add(eid)
        for task_id in sorted(set(inv_by_id) - set(bound_ids)):
            errors.append({"element_id": task_id, "field": "element_id",
                           "message": "BPMN element has no binding"})

        # ADR-050 + ADR-052 E1: a human/message output name must map to a SINGLE artifact across the run — a
        # from-artifact input source addresses a produced artifact by name (manifest input_map + PackValidator
        # resolution), so the same name pointing at DIFFERENT artifacts is ambiguous and rejected. But the same
        # name referencing the SAME artifact is legitimate: a revise loop has Task_TakeOrder and
        # Task_ReviseOrder both produce `order` (= art.dining.order); the runtime reads the latest write.
        # Capability outputs are mirrored from the capability and legitimately repeat (only flagged when the
        # collision involves a human/message binding on a DIFFERENT artifact).
        out_owner: Dict[str, Tuple[str, str, str]] = {}      # output name -> (element_id, executor_type, artifact_key)
        for sb in staged:
            for io in sb.outputs:
                art_key = (io.schema_ref or "").split("@", 1)[0]
                prior = out_owner.get(io.name)
                if prior and prior[0] != sb.element_id and prior[2] != art_key and \
                        ("human" in (prior[1], sb.executor_type) or "message" in (prior[1], sb.executor_type)):
                    errors.append({"element_id": sb.element_id, "field": "outputs",
                                   "message": f"output name '{io.name}' is already produced by '{prior[0]}' with a "
                                              f"different artifact ('{prior[2]}' vs '{art_key}') — a human/message "
                                              f"output name must reference a single artifact across the run"})
                out_owner.setdefault(io.name, (sb.element_id, sb.executor_type, art_key))

        if errors:
            raise TransitionError(422, {"error": "bindings_invalid", "errors": errors})

        # ADR-048 D4: fill each capability binding's input_sources from its BOUND capability's schema (never
        # a name guess) + the upstream producers' output schemas. This is authoritative — the capability is
        # chosen, so it works even when the BPMN element name diverges from the tool id. Only fills inputs the
        # operator left unset (a manually-edited source is preserved).
        await self._refine_binding_input_sources(s, staged)

        s.bindings = staged
        cleared = self._clear(s, {"dry_run"})
        s.state = OnboardingState.BINDINGS_SET
        s.last_cleared = cleared
        return await self.sessions.save(s)

    def _check_hitl_guard(self, b: BindingInput, side_effect: str, floor: Optional[str], errors: List[dict]) -> None:
        mode = b.hitl_mode
        if side_effect == "side_effectful" and not hitl_mode_at_least(mode, _APPROVE_ACTIONS):
            errors.append({
                "element_id": b.element_id, "field": "hitl_mode", "allowed_min_mode": "approve_actions",
                "message": "side-effectful capability requires HITL mode >= approve_actions",
            })
        if floor is not None and not hitl_mode_at_least(mode, floor):
            errors.append({
                "element_id": b.element_id, "field": "hitl_mode", "allowed_min_mode": floor,
                "message": f"HITL mode below capability floor '{floor}'",
            })

    @staticmethod
    def _staged_artifact_keys(s: OnboardingSession) -> set:
        """ADR-050: every artifact key a human/message binding IO may reference — staged (tool-inferred) +
        authored + the declared trigger."""
        keys = {sa.artifact_key for sa in s.staged_artifacts}
        keys |= {sa.artifact_key for sa in s.authored_artifacts}
        if s.trigger_artifact:
            keys.add(s.trigger_artifact.artifact_key)
        return keys

    def _validate_binding_io(self, b: BindingInput, ios: List[StagedBindingIO], staged_keys: set,
                             field: str, errors: List[dict]) -> List[StagedBindingIO]:
        """ADR-050: validate an operator-declared human/message binding's inputs/outputs — each ``schema_ref``
        must resolve to a staged/authored/trigger artifact, and names must be unique within this binding.
        Returns the validated list (mirrored onto the StagedBinding for emission into the manifest)."""
        out: List[StagedBindingIO] = []
        seen: set = set()
        for io in ios:
            if io.name in seen:
                errors.append({"element_id": b.element_id, "field": field,
                               "message": f"duplicate {field} name '{io.name}' on this binding"})
            seen.add(io.name)
            key = (io.schema_ref or "").split("@", 1)[0]
            if key not in staged_keys:
                errors.append({"element_id": b.element_id, "field": field,
                               "message": f"{field} '{io.name}' schema_ref '{io.schema_ref}' is not a staged, "
                                          f"authored, or trigger artifact"})
            out.append(io)
        return out

    # ------------------------------------------------------------------ #
    # 4b) declare_trigger — DECLARED trigger artifact schema (ADR-049)
    # ------------------------------------------------------------------ #
    async def declare_trigger(self, session_id: str, req: DeclareTriggerRequest, *, owner: str) -> OnboardingSession:
        """Declare the pack's trigger artifact schema. Not a state step: an enrichment callable once the process
        is known (≥ BPMN_ATTACHED). It flattens the DECLARED schema into ``trigger_fields`` (the Triage picker's
        source), stores it for registration + emission as ``ProcessPack.trigger``, and — because the trigger
        shape changed — clears any already-authored triage + downstream and regresses to BINDINGS_SET."""
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.BPMN_ATTACHED):
            raise TransitionError(409, "attach BPMN before declaring the trigger")
        errors: List[dict] = []
        if not _ART_ID_RE.match(req.artifact_key or ""):
            errors.append({"field": "artifact_key",
                           "message": "trigger artifact id must be art.<domain>.<name> (lowercase)"})
        if not isinstance(req.json_schema, dict) or req.json_schema.get("type", "object") != "object" \
                or not isinstance(req.json_schema.get("properties"), dict):
            errors.append({"field": "json_schema",
                           "message": "trigger schema must be a JSON object schema with a 'properties' map"})
        if errors:
            raise TransitionError(422, {"error": "trigger_invalid", "errors": errors})

        s.trigger_artifact = StagedArtifact(
            artifact_key=req.artifact_key, version=req.version, title=req.title,
            description=req.description, json_schema=req.json_schema,
        )
        s.trigger_fields = flatten_schema_fields(req.json_schema)

        # The trigger fields changed → any authored triage may reference stale fields. Clear it + downstream.
        cleared: List[str] = []
        if s.triage_rules:
            s.triage_rules = []
            cleared.append("triage_rules")
        cleared += self._clear(s, {"gateway_variables", "sod_policies", "dry_run"})
        if state_rank(s.state) > state_rank(OnboardingState.BINDINGS_SET):
            s.state = OnboardingState.BINDINGS_SET
        s.last_cleared = cleared
        return await self.sessions.save(s)

    async def declare_artifact(self, session_id: str, req: DeclareArtifactRequest, *, owner: str) -> OnboardingSession:
        """ADR-050: declare (upsert) an operator-authored artifact schema — one that is neither a tool's I/O
        nor the trigger (e.g. ``art.dining.order``, a human task's output shape). Not a state step: an
        enrichment callable once the process is known (≥ BPMN_ATTACHED). Stored on ``authored_artifacts``
        (upsert by key, surviving any capability re-staging), registered + listed among the pack artifacts at
        assemble, and referenceable by a human/message binding output. Clears the dry-run (a fresh schema may
        change data-flow validation); it never invalidates bindings by itself."""
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.BPMN_ATTACHED):
            raise TransitionError(409, "attach BPMN before declaring an artifact")
        errors: List[dict] = []
        if not _ART_ID_RE.match(req.artifact_key or ""):
            errors.append({"field": "artifact_key",
                           "message": "artifact id must be art.<domain>.<name> (lowercase)"})
        if not isinstance(req.json_schema, dict) or req.json_schema.get("type", "object") != "object" \
                or not isinstance(req.json_schema.get("properties"), dict):
            errors.append({"field": "json_schema",
                           "message": "artifact schema must be a JSON object schema with a 'properties' map"})
        if errors:
            raise TransitionError(422, {"error": "artifact_invalid", "errors": errors})

        sa = StagedArtifact(
            artifact_key=req.artifact_key, version=req.version, title=req.title,
            description=req.description, json_schema=req.json_schema,
        )
        s.authored_artifacts = [a for a in s.authored_artifacts if a.artifact_key != sa.artifact_key]
        s.authored_artifacts.append(sa)
        s.last_cleared = self._clear(s, {"dry_run"})
        return await self.sessions.save(s)

    async def refine_artifact(self, session_id: str, req: RefineArtifactRequest, *, owner: str) -> OnboardingSession:
        """ADR-054: persist a refined human-authored artifact schema (typed props, ``title`` labels, enums,
        ``required``). Unlike ``declare_artifact`` (which stores the request version verbatim), the version is
        resolved server-side the way the copilot does: reuse an already-registered version whose body is identical,
        else bump the minor above the highest registered — so the commit registers the CHANGED body at a new version
        instead of silently keeping the stale, immutable one (a same key+version re-register is a swallowed
        DuplicateError). The bindings that reference this artifact are re-pinned to the resolved version, so the
        activated pack's HITL form renders the operator's labels/dropdowns/typed inputs — not just at preview time."""
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.BPMN_ATTACHED):
            raise TransitionError(409, "attach BPMN before refining an artifact")
        errors: List[dict] = []
        if not isinstance(req.json_schema, dict) or req.json_schema.get("type", "object") != "object" \
                or not isinstance(req.json_schema.get("properties"), dict):
            errors.append({"field": "json_schema",
                           "message": "artifact schema must be a JSON object schema with a 'properties' map"})
        existing = next((a for a in s.authored_artifacts if a.artifact_key == req.artifact_key), None)
        if existing is None and not errors:
            errors.append({"field": "artifact_key",
                           "message": "only a human-authored artifact on this session can be refined"})
        if errors:
            raise TransitionError(422, {"error": "artifact_invalid", "errors": errors})

        version = await self._resolve_authored_version(req.artifact_key, req.json_schema)
        s.authored_artifacts = [a for a in s.authored_artifacts if a.artifact_key != req.artifact_key]
        s.authored_artifacts.append(StagedArtifact(
            artifact_key=req.artifact_key, version=version, title=(req.title or existing.title),
            description=existing.description, json_schema=req.json_schema))
        self._repoint_artifact_refs(s, req.artifact_key, version)
        s.last_cleared = self._clear(s, {"dry_run"})
        return await self.sessions.save(s)

    async def _resolve_authored_version(self, key: str, schema: Dict[str, Any]) -> str:
        """The version to register a refined artifact schema at: reuse an identically-registered version (no churn),
        else bump the minor above the highest registered (a same-version body change is immutable at commit)."""
        regs = await self.schemas.list_by_key(key)
        if not regs:
            return "1.0.0"
        for r in regs:
            if r.json_schema == schema:
                return r.version
        latest = Version(max(regs, key=lambda r: Version(r.version)).version)
        return f"{latest.major}.{latest.minor + 1}.0"

    @staticmethod
    def _repoint_artifact_refs(s: OnboardingSession, artifact_key: str, version: str) -> None:
        """Re-point every binding output / read-only-input ``schema_ref`` for this artifact key to the resolved
        version, so the composed + activated pack pins the refined body."""
        new_ref = f"{artifact_key}@^{version}"
        for b in s.bindings:
            for io in list(b.outputs or []) + list(b.inputs or []):
                if io.schema_ref and io.schema_ref.split("@", 1)[0] == artifact_key:
                    io.schema_ref = new_ref

    # ------------------------------------------------------------------ #
    # 5) set_triage — TRIAGE_SET
    # ------------------------------------------------------------------ #
    async def set_triage(self, session_id: str, req: SetTriageRequest, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.BINDINGS_SET) and s.state != OnboardingState.TRIAGE_SET:
            raise TransitionError(409, "set bindings before triage rules")
        if not req.triage_rules:
            raise TransitionError(422, {"error": "triage_invalid",
                                        "errors": [{"message": "at least one triage rule is required"}]})
        # ADR-049: schema-aware check against the pack's trigger shape — the DECLARED trigger schema when the
        # operator declared one (s.trigger_fields is flattened from it), else the deployment sample envelopes.
        # A field not on the trigger, or an op incompatible with its type, is a blocking error here — not a
        # silent "never triages" at runtime. Degrades to structural-only when no trigger shape is available.
        field_types = s.trigger_fields or infer_field_types(self._samples)
        errors: List[dict] = []
        for rule in req.triage_rules:
            try:
                parsed = TriageRule.model_validate({
                    "rule_id": rule.rule_id, "priority": rule.priority,
                    "description": rule.description, "when": rule.when,
                })
                check_predicate(parsed.when)
            except (PredicateSyntaxError, ValueError) as exc:
                errors.append({"rule_id": rule.rule_id, "message": f"invalid predicate: {exc}"})
                continue
            for f in validate_predicate(rule.when, field_types):
                errors.append({"rule_id": rule.rule_id, "field": f["field"], "code": f["code"],
                               "suggestion": f.get("suggestion"), "message": f["message"]})
        if errors:
            raise TransitionError(422, {"error": "triage_invalid", "errors": errors})

        s.triage_rules = list(req.triage_rules)
        cleared = self._clear(s, {"dry_run"})
        s.state = self._advance(s.state, OnboardingState.TRIAGE_SET)
        s.last_cleared = cleared
        return await self.sessions.save(s)

    # ------------------------------------------------------------------ #
    # 6) set_policies — POLICIES_SET
    # ------------------------------------------------------------------ #
    async def set_policies(self, session_id: str, req: SetPoliciesRequest, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.TRIAGE_SET) and s.state != OnboardingState.POLICIES_SET:
            raise TransitionError(409, "set triage rules before policies")
        s.gateway_variables = list(req.gateway_variables)
        s.sod_policies = list(req.sod_policies)
        # Roles are pack-local: the declared set plus any role referenced by a binding.
        declared = set(req.roles)
        for b in s.bindings:
            if b.hitl_role:
                declared.add(b.hitl_role)
            if b.executor_type == "human" and b.role:
                declared.add(b.role)
        s.roles = sorted(declared)
        # Metadata is optional enrichment; keep only entries for roles that actually exist.
        s.role_meta = {rid: meta for rid, meta in req.role_meta.items() if rid in declared}
        cleared = self._clear(s, {"dry_run"})
        s.state = self._advance(s.state, OnboardingState.POLICIES_SET)
        s.last_cleared = cleared
        return await self.sessions.save(s)

    # ------------------------------------------------------------------ #
    # 7) assemble — ASSEMBLED (compose manifest + dry-run the 7 stages)
    # ------------------------------------------------------------------ #
    async def assemble(self, session_id: str, *, owner: str) -> OnboardingSession:
        s = await self._editable(session_id, owner)
        if not s.at_least(OnboardingState.POLICIES_SET):
            raise TransitionError(409, "complete bindings, triage and policies before assembling")

        manifest, staged_descs, staged_regs = self._compose(s)
        cap_overlay = _CapOverlay(self.caps, staged_descs)
        schema_overlay = _SchemaOverlay(self.schemas, staged_regs)
        validator = PackValidator(cap_overlay, schema_overlay, profile=self.profile)  # type: ignore[arg-type]
        bpmn_xml = await self.bpmn.get_xml(self._staging_pk(s), s.basics.version)
        # ADR-049: hand Stage 7 the DECLARED trigger schema (staged, not yet registered) so triage validates
        # against the pack's own fields, not the deployment sample envelopes.
        report = await validator.validate(manifest, bpmn_xml, sample_envelopes=self._samples,
                                          trigger_schema=s.trigger_artifact.json_schema if s.trigger_artifact else None)

        s.dry_run_report = report.model_dump(mode="json")
        s.state = self._advance(s.state, OnboardingState.ASSEMBLED)
        s.last_cleared = []
        return await self.sessions.save(s)

    # ------------------------------------------------------------------ #
    # 8) commit — COMPLETED (ordered, idempotent chain; reuses the seeder's services)
    # ------------------------------------------------------------------ #
    async def commit(self, session_id: str, *, owner: str) -> OnboardingSession:
        s = await self.get(session_id, owner=owner)
        pk, ver = s.basics.pack_key, s.basics.version

        # Idempotent no-op: the pack is already live (matches the seeder's short-circuit).
        existing = await self.packs.get(pk, ver)
        if s.state == OnboardingState.COMPLETED or (existing and existing.status.value in ("active", "deprecated")):
            s.state = OnboardingState.COMPLETED
            s.result_pack = f"{pk}@{ver}"
            for step in s.commit_progress:
                step.status = "done"
            return await self.sessions.save(s)

        if not s.at_least(OnboardingState.ASSEMBLED):
            raise TransitionError(409, "assemble (and get a clean dry-run) before committing")

        manifest, _descs, staged_regs = self._compose(s)
        staged_arts = {sa.artifact_key: sa for sa in s.staged_artifacts}

        progress = [
            CommitStep(key="artifacts", label="Register artifact schemas"),
            CommitStep(key="capabilities", label="Register capabilities"),
            CommitStep(key="pack", label="Submit pack manifest"),
            CommitStep(key="bpmn", label="Attach BPMN definition"),
            CommitStep(key="validate", label="Server-side validation"),
            CommitStep(key="activate", label="Pin versions & activate"),
        ]
        s.commit_progress = progress

        def _mark(key: str, status: str, detail: Optional[str] = None) -> None:
            for st in progress:
                if st.key == key:
                    st.status = status
                    if detail:
                        st.detail = detail

        # 1) artifact schemas (409 already-exists ⇒ done)
        _mark("artifacts", "running")
        for reg in staged_regs:
            try:
                await register_schema(reg, self.schemas)
            except DuplicateError:
                pass
            except RegistrationError as exc:
                _mark("artifacts", "failed", "; ".join(exc.errors))
                await self.sessions.save(s)
                raise TransitionError(422, {"error": "artifact_registration_failed",
                                            "artifact": reg.artifact_key, "errors": exc.errors})
        _mark("artifacts", "done")

        # 2) capabilities
        _mark("capabilities", "running")
        for sc in s.staged_capabilities:
            desc = self._capability_descriptor(sc, staged_arts)
            try:
                await self.caps.insert(desc)
            except DuplicateError:
                pass
        for ref in s.reused_capability_refs:  # re-check reuse at commit
            ok, msg = await self._reused_ref_ok(ref)
            if not ok:
                _mark("capabilities", "failed", msg)
                await self.sessions.save(s)
                raise TransitionError(422, {"error": "reused_capability_unavailable", "ref": ref, "message": msg})
        _mark("capabilities", "done")

        # 3) pack draft
        _mark("pack", "running")
        try:
            await self.packs.insert(manifest)
        except DuplicateError:
            pass
        _mark("pack", "done")

        # 4) BPMN
        _mark("bpmn", "running")
        bpmn_xml = await self.bpmn.get_xml(self._staging_pk(s), ver)
        await self.bpmn.upsert(pk, ver, xml=bpmn_xml, sha256=s.bpmn.sha256)
        await self.packs.set_bpmn_sha(pk, ver, s.bpmn.sha256)  # keeps status draft
        _mark("bpmn", "done")

        # 5) validate (real repos)
        _mark("validate", "running")
        manifest = await self.packs.get(pk, ver)  # reload with current sha/status
        validator = PackValidator(self.caps, self.schemas, profile=self.profile)
        report = await validator.validate(manifest, bpmn_xml, sample_envelopes=self._samples,
                                          trigger_schema=s.trigger_artifact.json_schema if s.trigger_artifact else None)
        await self.packs.save_validation_report(pk, ver, report.model_dump(mode="json"))
        s.dry_run_report = report.model_dump(mode="json")
        if not report.ok:
            await self.packs.set_status(pk, ver, "draft")
            _mark("validate", "failed", ", ".join(report.error_codes()))
            s.state = OnboardingState.ASSEMBLED
            await self.sessions.save(s)
            raise TransitionError(422, {"error": "validation_failed", "errors": report.error_codes()})
        await self.packs.set_status(pk, ver, "validated")
        _mark("validate", "done")

        # 6) activate (pins ranges → exact, writes resolution sidecar)
        _mark("activate", "running")
        # ADR-027 Phase 2.5: pin the BPMN-derived minimum execution profile into resolution.
        _model, _ = parse_bpmn(bpmn_xml, manifest.process.process_id)
        prof = required_profile(_model) if _model is not None else "common_subset"
        resolution, resolved_caps = await resolve_pins(
            manifest, self.caps, self.schemas, required_execution_profile=prof)
        await self.packs.activate(pk, ver, resolved_caps=resolved_caps, resolution=resolution.to_doc())
        # Per-pack role metadata sidecar: enrich every derived role id with the operator's
        # authored label/description (falling back to a humanized label). Read by GET /roles.
        role_docs = [
            {
                "role_id": rid,
                "label": (s.role_meta.get(rid).label if s.role_meta.get(rid) else None) or humanize_role(rid),
                "description": (s.role_meta.get(rid).description if s.role_meta.get(rid) else None) or "",
            }
            for rid in s.roles
        ]
        await self.packs.save_pack_roles(pk, ver, role_docs)
        # ADR-056: publishing a version auto-deprecates every OTHER currently-active version of the same pack_key —
        # so the resolver routes NEW events to this version, while instances pinned to a prior version keep running
        # its immutable stored bundle. A no-op for a first onboard (this is the only active version of its key).
        for other in await self.packs.list_versions(pk):
            if other.version != ver and other.status.value == "active":
                await self.packs.set_status(pk, other.version, "deprecated")
        _mark("activate", "done")

        s.state = OnboardingState.COMPLETED
        s.result_pack = f"{pk}@{ver}"
        s.last_cleared = []
        return await self.sessions.save(s)

    # ================================================================== #
    # Internals
    # ================================================================== #
    async def _editable(self, session_id: str, owner: str) -> OnboardingSession:
        s = await self.get(session_id, owner=owner)
        if s.state == OnboardingState.COMPLETED:
            raise TransitionError(409, "session is completed and immutable")
        return s

    @staticmethod
    def _staging_pk(s: OnboardingSession) -> str:
        # Namespaced BPMN staging key so it never collides with a real pack's BPMN doc.
        return f"__onb__{s.session_id}"

    @staticmethod
    def _advance(current: OnboardingState, target: OnboardingState) -> OnboardingState:
        # Re-editing a later-or-equal step keeps position but drops any 'assembled' badge.
        if current == OnboardingState.ASSEMBLED and state_rank(target) < state_rank(OnboardingState.ASSEMBLED):
            return target
        return target if state_rank(target) > state_rank(current) else current

    @staticmethod
    def _clear(s: OnboardingSession, what: set) -> List[str]:
        cleared: List[str] = []
        if "bindings" in what and s.bindings:
            s.bindings = []
            cleared.append("bindings")
        if "gateway_variables" in what and s.gateway_variables:
            s.gateway_variables = []
            cleared.append("gateway_variables")
        if "sod_policies" in what and s.sod_policies:
            s.sod_policies = []
            cleared.append("sod_policies")
        if "dry_run" in what and s.dry_run_report is not None:
            s.dry_run_report = None
            cleared.append("dry_run_report")
        return cleared

    # -- BPMN parse + classification (ADR-027: classify, don't reject) -- #
    def _parse_and_check_bpmn(self, xml: str) -> Tuple[str, List[dict], Dict[str, Any]]:
        """Returns ``(process_id, hard_errors, inventory)``. Only genuinely-malformed input is a
        hard error (→ 422); documented/unknown elements — and parallel/chained gateways, which are
        an *activation*-time gate the runtime compiler still enforces — are non-blocking
        annotations surfaced via the coverage report on the inventory."""
        try:
            process_id = select_process_id(xml)  # shared selection (prefers isExecutable=true)
        except Exception as exc:  # noqa: BLE001
            return "", [{"code": "bpmn_parse_error", "message": f"could not read BPMN: {exc}"}], {}
        if not process_id:
            return "", [{"code": "bpmn_process_not_found", "message": "no <process> with an id"}], {}

        model, findings = parse_bpmn(xml, process_id)
        # Only error-severity findings block; documented (warning) / unknown (info) never do.
        hard_errors = [{"code": f.code, "element_id": f.element_id, "message": f.message}
                       for f in findings if f.severity == "error"]
        if model is None:
            return process_id, hard_errors or [{"code": "bpmn_parse_error", "message": "unparseable BPMN"}], {}
        if hard_errors:
            return process_id, hard_errors, {}

        service_tasks = [t for t, k in model.tasks.items() if k == "serviceTask"]
        user_tasks = [t for t, k in model.tasks.items() if k == "userTask"]
        cov = model.coverage()
        documented = [{"element_id": e.id, "kind": e.kind, "tier": e.tier}
                      for e in (cov["documented"] + cov["unknown"])]
        names = self._task_names(xml)
        return process_id, [], {
            # ADR-044 (Track 1): the full bindable set the runtime executes (do NOT re-derive — source
            # it from the parsed model's bindable_elements()). service/user tasks kept as legacy views.
            "bindable_elements": self._bindable_elements(model, names),
            "service_tasks": sorted(service_tasks),
            "user_tasks": sorted(user_tasks),
            "gateways": sorted(model.exclusive_gateways),
            "task_names": names,
            "documented_elements": documented,
            "coverage_counts": cov["counts"],
            # ADR-027 Phase 2.5: the min profile this diagram needs, derived here so the Review step
            # can flag "requires parallel profile" pre-activation (same value pinned at activation).
            "required_execution_profile": required_profile(model),
            # ADR-032 Phase 2.6: embedded sub-processes (id -> members) for the coverage grouping.
            "subprocesses": [{"id": s.id, "name": s.name, "member_ids": s.member_ids}
                             for s in model.subprocesses.values()],
        }

    @staticmethod
    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    # ADR-044 (Track 1): names for the full bindable set (not just service/user tasks).
    _NAMED_TAGS = (
        "serviceTask", "userTask", "sendTask", "scriptTask", "manualTask", "businessRuleTask",
        "receiveTask", "intermediateCatchEvent", "callActivity",
    )

    def _task_names(self, xml: str) -> Dict[str, str]:
        names: Dict[str, str] = {}
        try:
            root = ET.fromstring(xml)
        except Exception:  # noqa: BLE001
            return names
        for el in root.iter():
            if self._local(el.tag) in self._NAMED_TAGS:
                _id = el.get("id")
                if _id:
                    names[_id] = el.get("name") or _id
        return names

    def _bindable_elements(self, model, names: Dict[str, str]) -> List[Dict[str, Any]]:
        """The full bindable set (task kinds + message elements + callActivity) from the parsed model,
        each routed to its executor category + tagged with the badges the binding UI needs. The
        ``subProcess``/event-subprocess **containers** are never bindable (not in ``bindable_elements()``).
        """
        def _in_esp(eid: str) -> bool:
            s, seen = eid, set()
            while s and s not in seen:
                seen.add(s)
                if s in model.event_subprocesses:
                    return True
                s = model.element_scope.get(s)
            return False

        out: List[Dict[str, Any]] = []
        for eid, kind in model.bindable_elements().items():
            category = TASK_EXECUTOR_CATEGORY.get(kind, "capability")
            handler = model.compensation_handlers.get(eid)
            row: Dict[str, Any] = {
                "element_id": eid, "element_kind": kind, "category": category,
                "name": names.get(eid),
                "is_multi_instance": eid in model.multi_instance,
                "is_for_compensation": handler is not None,
                "compensation_primary": handler.primary_id if handler is not None else None,
                "in_event_subprocess": _in_esp(eid),
            }
            if category == "message":
                row["message_name"] = model.message_catch_events.get(eid) or model.receive_tasks.get(eid)
            elif category == "call":
                ca = model.call_activities.get(eid)
                row["called_pack"] = ca.target_pack if ca else None
                row["called_version"] = ca.version_range if ca else None
            out.append(row)
        return sorted(out, key=lambda r: r["element_id"])

    # -- capability lookups (staged + reused) -- #
    async def _reused_ref_ok(self, ref: str) -> Tuple[bool, str]:
        if "@" not in ref:
            return False, f"'{ref}' must be '<cap-id>@<range>'"
        ref_id, spec = ref.split("@", 1)
        versions = await self.caps.list_by_id(ref_id)
        if not versions:
            return False, f"no capability '{ref_id}' in the catalog"
        from amendia_contracts.common import CapabilityRef
        parsed = CapabilityRef.parse(ref)
        active_in_range = [v for v in versions if v.status.value == "active" and parsed.matches(v.version)]
        if not active_in_range:
            return False, f"no active version of '{ref_id}' satisfies '{spec}'"
        return True, ""

    async def _capability_io_and_policy(
        self, ref: str, s: OnboardingSession
    ) -> Optional[Tuple[str, Optional[str], List[StagedBindingIO], List[StagedBindingIO]]]:
        """(side_effect, min_hitl_floor, binding_inputs, binding_outputs) for a bound capability.

        Resolves against the session's staged mcp capabilities first, then the live catalog
        (reuse). Binding IO is mirrored from the capability so stage-5 reconciliation passes."""
        ref_id = ref.split("@", 1)[0]
        staged_arts = {sa.artifact_key: sa for sa in s.staged_artifacts}

        for sc in s.staged_capabilities:
            if sc.capability_id == ref_id:
                in_ver = staged_arts[sc.input_artifact_key].version if sc.input_artifact_key in staged_arts else sc.version
                out_ver = staged_arts[sc.output_artifact_key].version if sc.output_artifact_key in staged_arts else sc.version
                ins = [StagedBindingIO(name=sc.input_name, schema_ref=f"{sc.input_artifact_key}@^{in_ver}")]
                outs = [StagedBindingIO(name=sc.output_name, schema_ref=f"{sc.output_artifact_key}@^{out_ver}")]
                return sc.side_effect, sc.min_hitl_mode, ins, outs

        # reused capability from the live catalog
        from amendia_contracts.common import CapabilityRef
        try:
            parsed = CapabilityRef.parse(ref)
        except ValueError:
            return None
        versions = [v for v in await self.caps.list_by_id(ref_id)
                    if v.status.value == "active" and parsed.matches(v.version)]
        if not versions:
            return None
        from packaging.version import Version
        desc = max(versions, key=lambda v: Version(v.version))
        floor = desc.constraints.min_hitl_mode.value if (desc.constraints and desc.constraints.min_hitl_mode) else None
        ins = [StagedBindingIO(name=io.name, schema_ref=str(io.schema_)) for io in desc.inputs]
        outs = [StagedBindingIO(name=io.name, schema_ref=str(io.schema_)) for io in desc.outputs]
        return desc.side_effect.value, floor, ins, outs

    async def _refine_binding_input_sources(self, s: OnboardingSession, staged: List[StagedBinding]) -> None:
        """ADR-048 D4: derive each capability binding's field-level ``input_map`` from its bound
        ``capability_ref`` (authoritative — no element→capability name guessing). For each capability
        binding we read its own input artifact schema fields and each upstream capability producer's output
        schema fields (upstream elements come from the BPMN graph via ``inferred.upstream_caps``; the producer
        capability is whatever that element is BOUND to), then match input fields to upstream outputs / trigger
        paths. Only inputs the operator has NOT already sourced are filled — a manual override is preserved."""
        by_el = {b.element_id: b for b in staged}
        upstream_by_el: Dict[str, List[str]] = {}
        if s.inferred is not None:
            # ADR-050: source from the broader producer set (capabilities + human/message/call outputs),
            # capabilities first (upstream_caps) then any extra producers, deduped, so a capability input can
            # resolve to a human-authored artifact. Falls back to upstream_caps for pre-ADR-050 sessions.
            upstream_by_el = {}
            for ib in s.inferred.bindings:
                merged_ups: List[str] = list(ib.upstream_caps or [])
                for el in (ib.upstream_producers or []):
                    if el not in merged_ups:
                        merged_ups.append(el)
                upstream_by_el[ib.element_id] = merged_ups
        # ADR-050: authored + trigger schemas are producible fields too, so include them for field matching.
        staged_schema = {sa.artifact_key: sa.json_schema for sa in s.staged_artifacts}
        staged_schema.update({sa.artifact_key: sa.json_schema for sa in s.authored_artifacts})
        if s.trigger_artifact:
            staged_schema[s.trigger_artifact.artifact_key] = s.trigger_artifact.json_schema
        cache: Dict[str, List[str]] = {}

        async def fields_of(schema_ref: Optional[str]) -> List[str]:
            if not schema_ref:
                return []
            key = schema_ref.split("@", 1)[0]
            if key in cache:
                return cache[key]
            schema = staged_schema.get(key)
            if schema is None:                                 # reused capability → catalog schema
                regs = await self.schemas.list_by_key(key)
                if regs:
                    from packaging.version import Version
                    schema = max(regs, key=lambda r: Version(r.version)).json_schema
            props = schema.get("properties") if isinstance(schema, dict) else None
            out = list(props) if isinstance(props, dict) else []
            cache[key] = out
            return out

        # ADR-052: the DECLARED trigger's top-level field names (ADR-049) — used to name-match each input field
        # to a trigger field. Gate on the DECLARED trigger artifact, NOT on `s.trigger_fields`: before a trigger
        # is declared, `s.trigger_fields` holds the deployment's SAMPLE-derived fields (a foreign domain, e.g.
        # wire), which would match none of this pack's input fields and yield empty maps. When no trigger is
        # declared, treat the trigger as OPAQUE (None) so each input field still maps to a same-named trigger
        # path — never an empty composite.
        trigger_fields = ({k.split(".", 1)[0] for k in s.trigger_fields} if s.trigger_artifact else None)
        for b in staged:
            if b.executor_type != "capability" or not b.inputs:
                continue
            input_name = b.inputs[0].name
            if input_name in (b.input_sources or {}):           # operator already sourced this input
                continue
            in_fields = await fields_of(b.inputs[0].schema_ref)
            ups: List[tuple] = []
            for up_el in upstream_by_el.get(b.element_id, []):
                ub = by_el.get(up_el)
                # ADR-050: any upstream producer with a declared output (capability OR human/message/call)
                # is a candidate source — not just capabilities.
                if ub is None or not ub.outputs:
                    continue
                ups.append((ub.outputs[0].name, set(await fields_of(ub.outputs[0].schema_ref))))
            suggestion = suggest_binding_input_map(input_name, in_fields, ups, trigger_fields=trigger_fields)
            merged = dict(b.input_sources or {})
            for k, v in suggestion.items():
                merged.setdefault(k, v)
            b.input_sources = merged

    # -- manifest composition -- #
    def _staged_artifact_registration(self, sa: StagedArtifact) -> ArtifactSchemaRegistration:
        return ArtifactSchemaRegistration.model_validate({
            "artifact_key": sa.artifact_key, "version": sa.version, "title": sa.title,
            "description": sa.description, "json_schema": sa.json_schema,
            "compatibility": sa.compatibility, "status": "active",
        })

    # -- ADR-046 (Track 2): stage an inline-authored decision / reduce capability -- #
    def _stage_decision(self, spec, s: OnboardingSession, errors: List[dict]):
        """Validate a DMN table (shared checks) and stage a ``decision`` capability + its inferred
        verdict artifact. Returns ``(StagedArtifact, StagedCapability)`` or ``(None, None)`` on error."""
        try:
            table = parse_decision_table(spec.table)
        except Exception as exc:  # noqa: BLE001 — DmnError etc. → a field error, not a 500
            errors.append({"capability_id": spec.capability_id, "field": "table",
                           "message": f"malformed decision table: {exc}"})
            return None, None
        bad = [f for f in validate_table(table) if f.severity == "error"]
        if bad:
            for f in bad:
                errors.append({"capability_id": spec.capability_id, "field": "table",
                               "code": f.code, "message": f.message})
            return None, None
        # Verdict artifact: one field per output column. A string output with literal rule values →
        # an ENUM (the distinct 'then' values) so a downstream gateway branches on exact verdicts.
        props: Dict[str, Any] = {}
        required: List[str] = []
        for idx, o in enumerate(table.outputs):
            fld = o.name or f"out_{idx}"
            vals = []
            for r in table.rules:
                if idx < len(r.then):
                    v = r.then[idx]
                    if isinstance(v, (str, int, float, bool)) and v not in vals:
                        vals.append(v)
            if vals and (o.type in (None, "string")) and all(isinstance(v, str) for v in vals):
                props[fld] = {"enum": vals}
            else:
                props[fld] = {"type": _DMN_TYPE_JSON.get(o.type or "string", "string")}
            required.append(fld)
        schema, _w = normalize_artifact_schema(
            {"properties": props, "required": required},
            artifact_key=spec.output_artifact_key, version=spec.output_version)
        art = StagedArtifact(
            artifact_key=spec.output_artifact_key, version=spec.output_version,
            title=f"{spec.title or spec.capability_id} verdict", json_schema=schema)
        cap = StagedCapability(
            capability_id=spec.capability_id, version=spec.capability_version,
            title=spec.title or f"{spec.capability_id} (decision)", description=spec.description,
            kind="decision", side_effect="read_only",
            input_name=spec.input_name, input_artifact_key=spec.input_artifact_key,
            output_name=spec.output_name, output_artifact_key=spec.output_artifact_key,
            table=spec.table)
        return art, cap

    def _stage_reduce(self, spec, s: OnboardingSession, errors: List[dict]):
        """Validate a reduce config (shared checks) and stage a ``reduce`` capability + its inferred
        summary artifact. Returns ``(StagedArtifact, StagedCapability)`` or ``(None, None)`` on error."""
        try:
            config = parse_reduce_config(spec.config)
        except Exception as exc:  # noqa: BLE001
            errors.append({"capability_id": spec.capability_id, "field": "config",
                           "message": f"malformed reduce config: {exc}"})
            return None, None
        bad = [f for f in validate_reduce(config) if f.severity == "error"]
        if bad:
            for f in bad:
                errors.append({"capability_id": spec.capability_id, "field": "config",
                               "code": f.code, "message": f.message})
            return None, None
        # Summary artifact: the single output_field, typed by the op's result kind.
        fld = config.output_field or "result"
        schema, _w = normalize_artifact_schema(
            {"properties": {fld: {"type": _REDUCE_OP_TYPE.get(config.op, "string")}}, "required": [fld]},
            artifact_key=spec.output_artifact_key, version=spec.output_version)
        art = StagedArtifact(
            artifact_key=spec.output_artifact_key, version=spec.output_version,
            title=f"{spec.title or spec.capability_id} summary", json_schema=schema)
        cap = StagedCapability(
            capability_id=spec.capability_id, version=spec.capability_version,
            title=spec.title or f"{spec.capability_id} (reduce)", description=spec.description,
            kind="reduce", side_effect="read_only",
            input_name=spec.input_name, input_artifact_key=spec.input_artifact_key,
            output_name=spec.output_name, output_artifact_key=spec.output_artifact_key,
            config=spec.config)
        return art, cap

    def _capability_descriptor(
        self, sc: StagedCapability, staged_arts: Dict[str, StagedArtifact]
    ) -> CapabilityDescriptor:
        in_ver = staged_arts[sc.input_artifact_key].version if sc.input_artifact_key in staged_arts else sc.version
        out_ver = staged_arts[sc.output_artifact_key].version if sc.output_artifact_key in staged_arts else sc.version
        constraints: Dict[str, Any] = {}
        if sc.min_hitl_mode:
            constraints["min_hitl_mode"] = sc.min_hitl_mode
        # ADR-046 (Track 2): emit the runtime by kind — mcp (self-descriptive endpoint) or an inline
        # decision (DMN table) / reduce (config). Decision/reduce are always read_only.
        if sc.kind == "decision":
            runtime: Dict[str, Any] = {"kind": "decision", "table": sc.table or {}}
        elif sc.kind == "reduce":
            runtime = {"kind": "reduce", "config": sc.config or {}}
        else:
            runtime = {"kind": "mcp", "endpoint": sc.endpoint, "tools": [sc.tool],
                       "transport": sc.transport, "headers": sc.headers}
        payload: Dict[str, Any] = {
            "descriptor_version": "1.0", "capability_id": sc.capability_id, "version": sc.version,
            "title": sc.title, "description": sc.description, "kind": sc.kind, "side_effect": sc.side_effect,
            "idempotent": sc.idempotent,
            "inputs": [{"name": sc.input_name, "schema": f"{sc.input_artifact_key}@^{in_ver}"}],
            "outputs": [{"name": sc.output_name, "schema": f"{sc.output_artifact_key}@^{out_ver}"}],
            "runtime": runtime,
            "status": "active",
        }
        if constraints:
            payload["constraints"] = constraints
        return CapabilityDescriptor.model_validate(payload)

    def _compose(
        self, s: OnboardingSession
    ) -> Tuple[ProcessPackManifest, List[CapabilityDescriptor], List[ArtifactSchemaRegistration]]:
        # Defensive guard (batch-3): a binding with a missing required ref (e.g. a capability left
        # unselected, or a human with no role) would otherwise reach CapabilityRef/RoleId validation as a
        # raw TypeError → 500. Catch it here — assemble AND commit call _compose — as the platform's normal
        # field-level 422 naming the element, covering any already-saved (pre-guard) stuck session too.
        compose_errors: List[dict] = []
        for b in s.bindings:
            if b.executor_type == "capability" and not b.capability_ref:
                compose_errors.append({"element_id": b.element_id, "field": "capability_ref",
                                       "message": "capability executor has no capability bound"})
            elif b.executor_type == "human" and not b.role:
                compose_errors.append({"element_id": b.element_id, "field": "role",
                                       "message": "human executor has no role"})
            elif b.executor_type == "message" and not b.message_name:
                compose_errors.append({"element_id": b.element_id, "field": "message_name",
                                       "message": "message executor has no message_name"})
            elif b.executor_type == "call" and not b.call_pack:
                compose_errors.append({"element_id": b.element_id, "field": "call_pack",
                                       "message": "call executor has no callee pack"})
        if compose_errors:
            raise TransitionError(422, {"error": "bindings_invalid", "errors": compose_errors})

        staged_arts = {sa.artifact_key: sa for sa in s.staged_artifacts}
        descs = [self._capability_descriptor(sc, staged_arts) for sc in s.staged_capabilities]
        regs = [self._staged_artifact_registration(sa) for sa in s.staged_artifacts]
        reg_keys = {sa.artifact_key for sa in s.staged_artifacts}
        # ADR-050: operator-authored artifacts (human/message output shapes, etc.) are registered like any
        # staged schema and listed among the pack artifacts (their refs land via each binding's IO below).
        for sa in s.authored_artifacts:
            if sa.artifact_key not in reg_keys:
                regs.append(self._staged_artifact_registration(sa))
                reg_keys.add(sa.artifact_key)
        # ADR-049: a declared trigger artifact is registered like any staged schema, listed among the pack
        # artifacts, and emitted as the pack's ProcessPack.trigger (a pinned ArtifactRef).
        trigger_ref: Optional[str] = None
        if s.trigger_artifact:
            if s.trigger_artifact.artifact_key not in reg_keys:
                regs.append(self._staged_artifact_registration(s.trigger_artifact))
                reg_keys.add(s.trigger_artifact.artifact_key)
            trigger_ref = f"{s.trigger_artifact.artifact_key}@^{s.trigger_artifact.version}"

        # requires_capabilities: staged + reused (dedup by ref string).
        req_refs: List[str] = []
        for sc in s.staged_capabilities:
            req_refs.append(f"{sc.capability_id}@^{sc.version}")
        req_refs.extend(s.reused_capability_refs)
        seen_ref = set()
        requires = []
        for r in req_refs:
            if r not in seen_ref:
                seen_ref.add(r)
                requires.append({"ref": r})

        bindings: List[Dict[str, Any]] = []
        artifact_refs: List[str] = []
        for b in s.bindings:
            # ADR-044 (Track 1): emit the correct manifest Executor union member per binding category.
            if b.executor_type == "capability":
                executor = {"type": "capability", "capability": b.capability_ref}
            elif b.executor_type == "human":
                executor = {"type": "human", "role": b.role}
                if b.assist_capability_ref:
                    executor["assist_capability"] = b.assist_capability_ref
            elif b.executor_type == "message":
                executor = {"type": "message", "message_name": b.message_name}
            else:  # call (ADR-039) — the callee runs inline; no HITL of its own
                executor = {"type": "call", "pack": b.call_pack, "version": b.call_version or "^1.0.0",
                            "input_map": dict(b.input_map), "output_map": dict(b.output_map)}
            ins = [{"name": io.name, "schema": io.schema_ref, "required": io.required} for io in b.inputs]
            outs = [{"name": io.name, "schema": io.schema_ref, "required": io.required} for io in b.outputs]
            for io in (b.inputs + b.outputs):
                artifact_refs.append(io.schema_ref)
            binding_doc: Dict[str, Any] = {
                "element_id": b.element_id, "element_kind": b.element_kind,
                "executor": executor, "inputs": ins, "outputs": outs,
            }
            # ADR-048: per-input data sources → the manifest Binding.input_map. General across executor types:
            # a capability binding's auto-derived sources AND a human binding's operator-declared read-only
            # context inputs (mirroring ADR-050 outputs) both flow through here.
            if b.input_sources:
                binding_doc["input_map"] = dict(b.input_sources)
            # HITL is a capability/human concept; a message/call executor has no gate (contract omits it).
            if b.executor_type in ("capability", "human"):
                hitl: Dict[str, Any] = {"mode": b.hitl_mode}
                if b.hitl_role:
                    hitl["role"] = b.hitl_role
                binding_doc["hitl"] = hitl
            bindings.append(binding_doc)

        if trigger_ref:
            artifact_refs.append(trigger_ref)
        artifacts = sorted(set(artifact_refs))
        triage = [{"rule_id": r.rule_id, "priority": r.priority, "description": r.description, "when": r.when}
                  for r in s.triage_rules]
        gvars = [{"gateway_id": g.gateway_id, "variable": g.variable, "source_artifact": g.source_artifact}
                 for g in s.gateway_variables]
        policies = None
        if s.sod_policies:
            policies = {"separation_of_duties": [
                {"constraint": "distinct_actor", "elements": sod.elements} for sod in s.sod_policies
            ]}

        manifest = ProcessPackManifest.model_validate({
            "manifest_version": "1.0", "pack_key": s.basics.pack_key, "version": s.basics.version,
            "title": s.basics.title, "description": s.basics.description,
            "process": {"bpmn_file": s.bpmn.bpmn_file, "process_id": s.bpmn.process_id,
                        "bpmn_sha256": s.bpmn.sha256},
            "trigger": trigger_ref,  # ADR-049: declared trigger artifact (None ⇒ opaque envelope)
            "triage_rules": triage, "requires_capabilities": requires, "artifacts": artifacts,
            "bindings": bindings, "gateway_variables": gvars or None, "policies": policies,
            "status": "draft", "created_by": s.created_by,
        })
        return manifest, descs, regs
