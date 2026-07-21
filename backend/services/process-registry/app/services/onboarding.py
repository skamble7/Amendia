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

from app.services.inference import build_semantic_summary, infer_draft

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
    SetTriageRequest,
    StagedArtifact,
    StagedBinding,
    StagedBindingIO,
    StagedCapability,
    state_rank,
)
from app.services.activation import resolve_pins
from app.services.mcp_introspect import (
    McpConnectionError,
    McpIntrospector,
    infer_capability,
    introspect_response_tool,
    normalize_artifact_schema,
    sanitize_name as _san,
)
from app.services.registration import RegistrationError, register_schema
from app.validation.bpmn import compute_sha256
from app.validation.pack_validator import PackValidator
from app.validation.predicates import PredicateSyntaxError, check_predicate

_DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")
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
        domain = req.domain if _DOMAIN_RE.match(req.domain) else "payment"
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
        return IntrospectMcpResponse(
            endpoint=req.endpoint,
            transport=req.transport,
            tools=[introspect_response_tool(t, domain=domain) for t in tools],
        )

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
        domain = req.default_domain
        if not _DOMAIN_RE.match(domain):
            errors.append({"field": "default_domain", "message": "must match [a-z0-9_]+"})
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
        )
        return await self.sessions.insert(session)

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

        if errors:
            raise TransitionError(422, {"error": "capabilities_invalid", "errors": errors})

        s.staged_artifacts = staged_arts
        s.staged_capabilities = staged_caps
        s.reused_capability_refs = reused
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
            if b.executor_type == "capability" and b.capability_ref:
                cap_io = await self._capability_io_and_policy(b.capability_ref, s)
                if cap_io is None:
                    errors.append({"element_id": b.element_id, "field": "capability_ref",
                                   "message": f"capability '{b.capability_ref}' is not staged or active"})
                else:
                    side_effect, floor, io_inputs, io_outputs = cap_io
                    self._check_hitl_guard(b, side_effect, floor, errors)
            elif b.executor_type == "message":
                # ADR-031: the message this element awaits (advisory BPMN name pre-fills; operator confirms).
                message_name = b.message_name or inv.message_name
                if not message_name:
                    errors.append({"element_id": b.element_id, "field": "message_name",
                                   "message": "message executor requires a message_name"})
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
                input_map=input_map, output_map=output_map, inputs=io_inputs, outputs=io_outputs,
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

        if errors:
            raise TransitionError(422, {"error": "bindings_invalid", "errors": errors})

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
        report = await validator.validate(manifest, bpmn_xml, sample_envelopes=self._samples)

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
        report = await validator.validate(manifest, bpmn_xml, sample_envelopes=self._samples)
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
        staged_arts = {sa.artifact_key: sa for sa in s.staged_artifacts}
        descs = [self._capability_descriptor(sc, staged_arts) for sc in s.staged_capabilities]
        regs = [self._staged_artifact_registration(sa) for sa in s.staged_artifacts]

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
            # HITL is a capability/human concept; a message/call executor has no gate (contract omits it).
            if b.executor_type in ("capability", "human"):
                hitl: Dict[str, Any] = {"mode": b.hitl_mode}
                if b.hitl_role:
                    hitl["role"] = b.hitl_role
                binding_doc["hitl"] = hitl
            bindings.append(binding_doc)

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
            "triage_rules": triage, "requires_capabilities": requires, "artifacts": artifacts,
            "bindings": bindings, "gateway_variables": gvars or None, "policies": policies,
            "status": "draft", "created_by": s.created_by,
        })
        return manifest, descs, regs
