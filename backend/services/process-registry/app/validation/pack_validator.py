# app/validation/pack_validator.py
"""Cross-contract pack validation pipeline (the heart of the registry).

Seven ordered stages (contracts doc validation matrix / reference §9), each appending
findings to a single ValidationReport. Later stages emit ``stage_skipped`` when a hard
prerequisite (a parseable BPMN) is missing. Deterministic output.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from packaging.version import Version

from amendia_bpmn import TASK_EXECUTOR_CATEGORY, compilability_findings
from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.common import HitlMode, hitl_mode_at_least
from amendia_contracts.process_pack import ProcessPackManifest
from app.validation.deep_agent import validate_deep_agent_bindings
from app.validation.decision import validate_decision_bindings
from app.validation.reduce import validate_reduce_bindings
from app.dal.artifact_schema_repo import ArtifactSchemaRepository
from app.dal.capability_repo import CapabilityRepository
from app.validation.bpmn import BpmnModel, parse_and_validate
from app.validation.predicates import PredicateSyntaxError, check_predicate, evaluate
from app.validation.report import Severity, ValidationReport

APPROVE_ACTIONS = HitlMode.APPROVE_ACTIONS


def _forward_reach(model: BpmnModel) -> Dict[str, set]:
    adj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    for f in model.flows:
        if f.source in adj and f.target in adj:
            adj[f.source].append(f.target)
    reach: Dict[str, set] = {}
    for n in model.node_ids:
        seen, stack = set(), [n]
        while stack:
            x = stack.pop()
            for y in adj.get(x, []):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        reach[n] = seen
    return reach


class PackValidator:
    def __init__(
        self, cap_repo: CapabilityRepository, schema_repo: ArtifactSchemaRepository,
        *, profile: str = "common_subset", pack_repo: Optional[object] = None,
    ) -> None:
        self.caps = cap_repo
        self.schemas = schema_repo
        self.profile = profile  # ADR-027 Phase 2: which BPMN constructs may activate
        self.packs = pack_repo  # ADR-039: needed to validate/pin callActivity callees (cross-pack)

    async def validate(
        self,
        manifest: ProcessPackManifest,
        bpmn_xml: Optional[str],
        *,
        sample_envelopes: Optional[List[dict]] = None,
    ) -> ValidationReport:
        report = ValidationReport(pack_key=manifest.pack_key, pack_version=manifest.version)
        # Stage 1
        model = await self._stage1_bpmn(manifest, bpmn_xml, report)
        # Stage 3 (resolve caps) is needed by 4 & 5, so run it before them regardless of BPMN.
        resolved_caps = await self._stage3_capabilities(manifest, report)
        # Stage 2
        if model is not None:
            self._stage2_bijection(manifest, model, report)
        else:
            report.error("stage_skipped", stage=2, message="binding bijection skipped: no valid BPMN")
        # Stage 4
        self._stage4_hitl_policy(manifest, resolved_caps, report)
        # ADR-040: an interrupting timer boundary on a running serviceTask is safe only for a read_only
        # capability (interrupting a side effect is compensation — deferred). Cross-contract check.
        if model is not None:
            self._validate_timer_boundary_side_effect(manifest, model, resolved_caps, report)
        # ADR-041: an interrupting timer boundary on a subProcess cancels the whole scope — safe only if
        # the scope contains autonomous read_only capabilities (no side effects, no HITL gates).
        if model is not None:
            self._validate_subprocess_timer_scope(manifest, model, resolved_caps, report)
        # ADR-043 (Item G): compensation — a compensable primary must be side-effectful (undoing a
        # read-only step is meaningless), and its handler must be a bound capability.
        if model is not None:
            self._validate_compensation(manifest, model, resolved_caps, report)
        # Stage 5
        if model is not None:
            await self._stage5_artifacts_io(manifest, model, resolved_caps, report)
        else:
            report.error("stage_skipped", stage=5, message="artifact/IO checks skipped: no valid BPMN")
        # Stage 6
        if model is not None:
            await self._stage6_gateway_vars(manifest, model, report)
        else:
            report.error("stage_skipped", stage=6, message="gateway-variable checks skipped: no valid BPMN")
        # ADR-037: native DMN decision tables (validate every decision-kind binding's inline table).
        if model is not None:
            await self._validate_decision_tables(manifest, model, resolved_caps, report)
        # ADR-039: cross-pack composition (validate every callActivity's callee + IO + call graph).
        if model is not None and self.packs is not None:
            from app.validation.call import validate_call_bindings
            await validate_call_bindings(manifest, model, self.packs, report)
        # ADR-038: collection-reduction configs (validate every reduce-kind binding).
        if model is not None:
            await self._validate_reduce_configs(manifest, model, resolved_caps, report)
        # Stage 7
        await self._stage7_policies_triage(manifest, model, report, sample_envelopes or [])
        return report.finalize()

    # ------------------------------------------------------------------ #
    # Stage 1 — BPMN
    # ------------------------------------------------------------------ #
    async def _stage1_bpmn(
        self, manifest: ProcessPackManifest, bpmn_xml: Optional[str], report: ValidationReport
    ) -> Optional[BpmnModel]:
        if not bpmn_xml:
            report.error("bpmn_missing", stage=1, message="no BPMN uploaded for this pack")
            return None
        model = parse_and_validate(
            bpmn_xml,
            expected_process_id=manifest.process.process_id,
            expected_sha256=manifest.process.bpmn_sha256,
            report=report,
            profile=self.profile,
        )
        # ADR-027 §1a / Phase 2: block *activation* of packs the runtime compiler cannot run under
        # this profile (parallel/chained gateways, bad task/start arity) — the same structural gate
        # the compiler raises off. Attach stays permissive (onboarding surfaces these as coverage).
        if model is not None:
            for f in compilability_findings(model, profile=self.profile):
                report.error(f.code, stage=1, element_id=f.element_id, message=f.message)
        return model

    # ------------------------------------------------------------------ #
    # Stage 2 — binding ↔ task bijection
    # ------------------------------------------------------------------ #
    def _stage2_bijection(self, manifest: ProcessPackManifest, model: BpmnModel, report: ValidationReport) -> None:
        binding_ids = [b.element_id for b in manifest.bindings]
        # ADR-031/033: bindable elements include message catch / receive + the full task set. The
        # shared TASK_EXECUTOR_CATEGORY map drives the executor-kind check for every task kind.
        bindable = model.bindable_elements()
        expected_executor = TASK_EXECUTOR_CATEGORY
        seen = set()
        for b in manifest.bindings:
            if b.element_id in seen:
                report.error("duplicate_binding", stage=2, element_id=b.element_id,
                             message=f"more than one binding for element '{b.element_id}'")
            seen.add(b.element_id)
            kind = bindable.get(b.element_id)
            if kind is None:
                report.error("orphan_binding", stage=2, element_id=b.element_id,
                             message=f"binding references '{b.element_id}' which is not a bindable BPMN element")
                continue
            if kind != b.element_kind:
                report.error("binding_kind_mismatch", stage=2, element_id=b.element_id,
                             message=f"binding element_kind '{b.element_kind}' != BPMN kind '{kind}'")
            etype = b.executor.type
            if etype != expected_executor.get(kind):
                report.error("executor_kind_mismatch", stage=2, element_id=b.element_id,
                             message=f"{kind} must bind a {expected_executor.get(kind)} executor, got '{etype}'")
            if etype == "message" and not getattr(b.executor, "message_name", None):
                report.error("message_name_missing", stage=2, element_id=b.element_id,
                             message="message binding requires a non-empty message_name")
        for el_id in sorted(set(bindable) - set(binding_ids)):
            report.error("unbound_task", stage=2, element_id=el_id,
                         message=f"BPMN element '{el_id}' ({bindable[el_id]}) has no binding")

    # ------------------------------------------------------------------ #
    # Stage 3 — capability resolution
    # ------------------------------------------------------------------ #
    async def _resolve_capability(self, ref) -> Tuple[str, Optional[CapabilityDescriptor]]:
        versions = await self.caps.list_by_id(ref.ref_id)
        if not versions:
            return "unknown_id", None
        in_range = [v for v in versions if ref.matches(v.version)]
        if not in_range:
            return "no_version_in_range", None
        active = [v for v in in_range if v.status.value == "active"]
        if not active:
            return "only_deprecated", None
        pinned = max(active, key=lambda v: Version(v.version))
        return "ok", pinned

    async def _stage3_capabilities(
        self, manifest: ProcessPackManifest, report: ValidationReport
    ) -> Dict[str, CapabilityDescriptor]:
        resolved: Dict[str, CapabilityDescriptor] = {}
        declared = {rc.ref.ref_id for rc in manifest.requires_capabilities}

        async def resolve(ref, element_id: Optional[str], what: str):
            status, desc = await self._resolve_capability(ref)
            if status == "unknown_id":
                report.error("unknown_capability", stage=3, element_id=element_id,
                             message=f"{what} '{ref}': no capability with id '{ref.ref_id}' registered")
            elif status == "no_version_in_range":
                report.error("capability_no_version_in_range", stage=3, element_id=element_id,
                             message=f"{what} '{ref}': no registered version satisfies the range")
            elif status == "only_deprecated":
                report.error("capability_only_deprecated", stage=3, element_id=element_id,
                             message=f"{what} '{ref}': only deprecated versions satisfy the range")
            elif desc is not None:
                resolved[ref.ref_id] = desc

        for rc in manifest.requires_capabilities:
            await resolve(rc.ref, None, "requires_capabilities ref")

        for b in manifest.bindings:
            ex = b.executor
            if ex.type == "capability":
                if ex.capability.ref_id not in declared:
                    report.warning("capability_not_declared", stage=3, element_id=b.element_id,
                                   message=f"binding capability '{ex.capability.ref_id}' is not in requires_capabilities")
                await resolve(ex.capability, b.element_id, "binding capability")
            elif ex.type == "human" and ex.assist_capability is not None:
                if ex.assist_capability.ref_id not in declared:
                    report.warning("capability_not_declared", stage=3, element_id=b.element_id,
                                   message=f"assist_capability '{ex.assist_capability.ref_id}' is not in requires_capabilities")
                await resolve(ex.assist_capability, b.element_id, "assist_capability")
        return resolved

    # ------------------------------------------------------------------ #
    # Stage 4 — HITL & side-effect policy
    # ------------------------------------------------------------------ #
    def _stage4_hitl_policy(
        self, manifest: ProcessPackManifest, resolved: Dict[str, CapabilityDescriptor], report: ValidationReport
    ) -> None:
        for b in manifest.bindings:
            if b.hitl is None:  # ADR-031: message bindings have no HITL gate — nothing to check here
                continue
            mode = b.hitl.mode
            if mode is not HitlMode.NONE and b.hitl.role is None:
                report.error("hitl_role_missing", stage=4, element_id=b.element_id,
                             message=f"hitl mode '{mode.value}' requires a role")
            ex = b.executor
            desc = resolved.get(ex.capability.ref_id) if ex.type == "capability" else None
            if desc is None:
                continue
            if desc.side_effect.value == "side_effectful" and not hitl_mode_at_least(mode, APPROVE_ACTIONS):
                report.error("side_effect_requires_approve_actions", stage=4, element_id=b.element_id,
                             message=f"side-effectful capability '{desc.capability_id}' bound at "
                                     f"'{mode.value}'; must be >= approve_actions")
            floor = desc.constraints.min_hitl_mode if desc.constraints else None
            if floor is not None and not hitl_mode_at_least(mode, floor):
                report.error("hitl_below_capability_floor", stage=4, element_id=b.element_id,
                             message=f"binding hitl '{mode.value}' is below capability min_hitl_mode '{floor.value}'")

        # deep_agent-specific rules (ADR-021): HITL gate required, read_only-or-justified,
        # tools resolve, nemoclaw-mode required. (Runs once, after the per-binding loop.)
        validate_deep_agent_bindings(manifest, resolved, report)

    # ------------------------------------------------------------------ #
    # ADR-040 — running-task timer boundary safety (read_only only)
    # ------------------------------------------------------------------ #
    def _validate_timer_boundary_side_effect(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        """A capability serviceTask host that carries an interrupting timer boundary self-cancels its
        own execution on breach (ADR-040). That is safe only for a ``read_only`` binding — interrupting
        a side-effectful capability may leave a half-applied side effect (compensation, deferred)."""
        bindings = {b.element_id: b for b in manifest.bindings}
        for host, bt in model.boundary_timers.items():
            if TASK_EXECUTOR_CATEGORY.get(model.tasks.get(host)) != "capability":
                continue  # a HITL host (userTask/manualTask) uses the idle-gate SLA — unaffected
            b = bindings.get(host)
            if b is None or getattr(b.executor, "type", None) != "capability":
                continue
            desc = resolved.get(b.executor.capability.ref_id)
            if desc is not None and desc.side_effect.value == "side_effectful":
                report.error("bpmn_timer_boundary_side_effect_unsupported", stage=4, element_id=host,
                             message=f"timer boundary '{bt.id}' on serviceTask '{host}' is bound to a "
                                     f"side-effectful capability '{desc.capability_id}' — interrupting a "
                                     f"side effect is unsafe (compensation, deferred); only read_only is "
                                     f"supported (ADR-040)")

    def _validate_subprocess_timer_scope(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        """An interrupting timer boundary on a subProcess abandons the whole running scope on breach
        (ADR-041). ADR-042 generalizes the scope to the **whole process** — a process-level timer event
        sub-process guards every top-level (and nested) task. Either way it is safe only if every task in
        the scope is an **autonomous read_only capability**: a side-effectful task may leave a half-applied
        side effect (compensation, deferred to G), and a HITL gate is the idle-park SLA case (ADR-029), not
        scope cancellation. The event sub-process body (the handler) is NOT part of the guarded scope."""
        def _in_esp_body(tid: str) -> bool:
            s = tid
            seen = set()
            while s and s not in seen:
                seen.add(s)
                if s in model.event_subprocesses:
                    return True
                s = model.element_scope.get(s)
            return False

        def _in_scope(tid: str, sid: str) -> bool:
            if _in_esp_body(tid):
                return False                       # the ESP body is the handler, not the guarded scope
            if sid == model.process_id:            # ADR-042: a process-level timer ESP guards everything
                return True
            s = model.element_scope.get(tid)
            seen = set()
            while s and s != model.process_id and s not in seen:
                if s == sid:
                    return True
                seen.add(s)
                s = model.element_scope.get(s)
            return False

        bindings = {b.element_id: b for b in manifest.bindings}
        for sid in model.boundary_timers:
            # A subProcess timer scope (ADR-041) or the whole-process scope of a process-level timer
            # event sub-process (ADR-042). A single-node serviceTask timer host (ADR-040) is skipped.
            if sid not in model.subprocesses and sid != model.process_id:
                continue
            for tid, kind in model.tasks.items():
                if not _in_scope(tid, sid):
                    continue
                b = bindings.get(tid)
                hitl_gated = TASK_EXECUTOR_CATEGORY.get(kind) == "human" or (
                    b is not None and b.hitl is not None
                    and (b.hitl.mode.value if hasattr(b.hitl.mode, "value") else str(b.hitl.mode)) != "none")
                if hitl_gated:
                    report.error("bpmn_subprocess_timer_scope_hitl_unsupported", stage=4, element_id=tid,
                                 message=f"task '{tid}' inside interrupting-timer subProcess '{sid}' is a "
                                         f"HITL gate — scope cancellation of a parked gate is out of scope "
                                         f"(the idle-gate SLA is ADR-029)")
                if b is not None and getattr(b.executor, "type", None) == "capability":
                    desc = resolved.get(b.executor.capability.ref_id)
                    if desc is not None and desc.side_effect.value == "side_effectful":
                        report.error("bpmn_subprocess_boundary_side_effect_unsupported", stage=4,
                                     element_id=tid,
                                     message=f"side-effectful task '{tid}' inside interrupting-timer "
                                             f"subProcess '{sid}' — cancelling committed side effects is "
                                             f"compensation (deferred to Item G)")

    def _validate_compensation(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        """ADR-043 (Item G): the compensable **primary** of each compensation pairing must be bound to a
        **side-effectful** capability (compensating a read-only step is meaningless), and the **handler**
        (``isForCompensation`` undo activity) must be a bound capability."""
        bindings = {b.element_id: b for b in manifest.bindings}
        for handler_id, pairing in model.compensation_handlers.items():
            hb = bindings.get(handler_id)
            if hb is None or getattr(hb.executor, "type", None) != "capability":
                report.error("bpmn_compensation_handler_unbound", stage=4, element_id=handler_id,
                             message=f"compensation handler '{handler_id}' (isForCompensation) must be "
                                     f"bound to an undo capability")
            primary = pairing.primary_id
            pb = bindings.get(primary)
            if pb is not None and getattr(pb.executor, "type", None) == "capability":
                desc = resolved.get(pb.executor.capability.ref_id)
                if desc is not None and desc.side_effect.value != "side_effectful":
                    report.error("bpmn_compensation_handler_not_side_effect", stage=4, element_id=primary,
                                 message=f"compensable activity '{primary}' is bound to a "
                                         f"{desc.side_effect.value} capability — only a side-effectful "
                                         f"activity can be compensated (there is nothing to undo otherwise)")

    # ------------------------------------------------------------------ #
    # Stage 5 — artifacts & IO
    # ------------------------------------------------------------------ #
    async def _resolve_artifact(self, ref) -> Tuple[str, Optional[object]]:
        versions = await self.schemas.list_by_key(ref.ref_id)
        if not versions:
            return "unknown_id", None
        in_range = [v for v in versions if ref.matches(v.version)]
        if not in_range:
            return "no_version_in_range", None
        active = [v for v in in_range if v.status.value == "active"]
        if not active:
            return "only_deprecated", None
        return "ok", max(active, key=lambda v: Version(v.version))

    async def _artifact_error(self, ref, element_id, what, report) -> bool:
        status, _ = await self._resolve_artifact(ref)
        if status == "unknown_id":
            report.error("unknown_artifact_schema", stage=5, element_id=element_id,
                         message=f"{what} '{ref}': no artifact schema '{ref.ref_id}' registered")
        elif status == "no_version_in_range":
            report.error("artifact_no_version_in_range", stage=5, element_id=element_id,
                         message=f"{what} '{ref}': no registered version satisfies the range")
        elif status == "only_deprecated":
            report.error("artifact_only_deprecated", stage=5, element_id=element_id,
                         message=f"{what} '{ref}': only deprecated versions satisfy the range")
        else:
            return True
        return False

    async def _ranges_overlap(self, ref_a, ref_b) -> bool:
        versions = await self.schemas.list_by_key(ref_a.ref_id)
        return any(ref_a.matches(v.version) and ref_b.matches(v.version) for v in versions)

    async def _stage5_artifacts_io(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        for ref in manifest.artifacts:
            await self._artifact_error(ref, None, "artifacts[]", report)

        for b in manifest.bindings:
            for io in (b.inputs + b.outputs):
                await self._artifact_error(io.schema_, b.element_id, f"binding IO '{io.name}'", report)

        # resolved capability IO
        for desc in resolved.values():
            for io in (desc.inputs + desc.outputs):
                await self._artifact_error(io.schema_, None, f"capability {desc.capability_id} IO '{io.name}'", report)

        # IO reconciliation binding <-> capability (capability executor or human assist)
        for b in manifest.bindings:
            desc = None
            ex = b.executor
            if ex.type == "capability":
                desc = resolved.get(ex.capability.ref_id)
            elif ex.type == "human" and ex.assist_capability is not None:
                desc = resolved.get(ex.assist_capability.ref_id)
            if desc is None:
                continue
            for side, b_ios, c_ios in (("inputs", b.inputs, desc.inputs), ("outputs", b.outputs, desc.outputs)):
                b_map = {io.name: io for io in b_ios}
                c_map = {io.name: io for io in c_ios}
                if set(b_map) != set(c_map):
                    report.error("binding_io_mismatch", stage=5, element_id=b.element_id,
                                 message=f"{side} name set {sorted(b_map)} != capability "
                                         f"{desc.capability_id} {side} {sorted(c_map)}")
                for name in set(b_map) & set(c_map):
                    if not await self._ranges_overlap(b_map[name].schema_, c_map[name].schema_):
                        report.error("binding_io_schema_incompatible", stage=5, element_id=b.element_id,
                                     path=f"/{side}/{name}",
                                     message=f"{side} '{name}': binding schema '{b_map[name].schema_}' and "
                                             f"capability schema '{c_map[name].schema_}' share no registered version")

        # input produced upstream (warning)
        reach = _forward_reach(model)
        producers: Dict[str, List[str]] = {}
        for b in manifest.bindings:
            for io in b.outputs:
                producers.setdefault(io.name, []).append(b.element_id)
        for b in manifest.bindings:
            for io in b.inputs:
                ok = any(b.element_id in reach.get(p, set()) for p in producers.get(io.name, []) if p != b.element_id)
                if not ok:
                    report.warning("unproduced_input", stage=5, element_id=b.element_id,
                                   message=f"input '{io.name}' is not produced by any upstream binding "
                                           f"(assumed seed state)")

    # ------------------------------------------------------------------ #
    # Stage 6 — gateway variables
    # ------------------------------------------------------------------ #
    async def _latest_active_schema(self, artifact_key: str):
        versions = [v for v in await self.schemas.list_by_key(artifact_key) if v.status.value == "active"]
        if not versions:
            return None
        return max(versions, key=lambda v: Version(v.version))

    def _required_path_ok(self, json_schema: dict, segments: List[str]) -> Tuple[bool, Optional[str]]:
        node = json_schema
        pointer = ""
        for seg in segments:
            required = node.get("required", []) if isinstance(node, dict) else []
            props = node.get("properties", {}) if isinstance(node, dict) else {}
            pointer += f"/properties/{seg}"
            if seg not in props:
                return False, pointer
            if seg not in required:
                return False, f"{pointer} (not required)"
            node = props[seg]
        return True, None

    async def _stage6_gateway_vars(
        self, manifest: ProcessPackManifest, model: BpmnModel, report: ValidationReport
    ) -> None:
        gvars = manifest.gateway_variables or []
        by_gateway: Dict[str, list] = {}
        for gv in gvars:
            by_gateway.setdefault(gv.gateway_id, []).append(gv)

        for gw in model.exclusive_gateways:
            if gw not in by_gateway:
                report.warning("gateway_without_variable", stage=6, element_id=gw,
                               message=f"exclusiveGateway '{gw}' declares no gateway_variables entry")

        reach = _forward_reach(model)
        producers: Dict[str, List[str]] = {}
        for b in manifest.bindings:
            for io in b.outputs:
                producers.setdefault(io.name, []).append(b.element_id)

        for gv in gvars:
            if gv.gateway_id not in model.node_ids or gv.gateway_id not in model.exclusive_gateways:
                report.error("gateway_variable_unknown_gateway", stage=6, element_id=gv.gateway_id,
                             message=f"gateway_variables references unknown exclusiveGateway '{gv.gateway_id}'")
                continue
            segs = gv.variable.split(".")
            state_name, field_path = segs[0], segs[1:]
            upstream = any(gv.gateway_id in reach.get(p, set()) for p in producers.get(state_name, []))
            if not upstream:
                report.error("gateway_variable_unproduced", stage=6, element_id=gv.gateway_id,
                             message=f"variable '{gv.variable}': state '{state_name}' is not produced by any "
                                     f"binding upstream of the gateway")
                continue
            schema = await self._latest_active_schema(gv.source_artifact)
            if schema is None:
                report.error("gateway_variable_schema_missing", stage=6, element_id=gv.gateway_id,
                             message=f"source_artifact '{gv.source_artifact}' has no active registered schema")
                continue
            if field_path:
                ok, pointer = self._required_path_ok(schema.json_schema, field_path)
                if not ok:
                    report.error("gateway_variable_not_required", stage=6, element_id=gv.gateway_id,
                                 path=pointer,
                                 message=f"variable '{gv.variable}': field is not required at every level in "
                                         f"'{gv.source_artifact}'")

    # ------------------------------------------------------------------ #
    # ADR-037 — native DMN decision tables
    # ------------------------------------------------------------------ #
    async def _validate_decision_tables(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        """Pre-fetch each decision binding's pinned verdict schema, then run the shared DMN checks."""
        output_schemas: Dict[str, dict] = {}
        for b in manifest.bindings:
            ex = b.executor
            if ex.type != "capability":
                continue
            desc = resolved.get(ex.capability.ref_id)
            if desc is None or (desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)) != "decision":
                continue
            for io in b.outputs:
                schema = await self._latest_active_schema(io.schema_.ref_id)
                if schema is not None:
                    output_schemas[io.schema_.ref_id] = schema.json_schema
        validate_decision_bindings(manifest, model, resolved, output_schemas, report)

    async def _validate_reduce_configs(
        self, manifest: ProcessPackManifest, model: BpmnModel,
        resolved: Dict[str, CapabilityDescriptor], report: ValidationReport,
    ) -> None:
        """Pre-fetch each reduce binding's pinned input + summary schemas, then run the shared checks."""
        input_schemas: Dict[str, dict] = {}
        output_schemas: Dict[str, dict] = {}
        for b in manifest.bindings:
            ex = b.executor
            if ex.type != "capability":
                continue
            desc = resolved.get(ex.capability.ref_id)
            if desc is None or (desc.kind.value if hasattr(desc.kind, "value") else str(desc.kind)) != "reduce":
                continue
            for io, sink in [(io, input_schemas) for io in b.inputs] + [(io, output_schemas) for io in b.outputs]:
                schema = await self._latest_active_schema(io.schema_.ref_id)
                if schema is not None:
                    sink[io.schema_.ref_id] = schema.json_schema
        validate_reduce_bindings(manifest, model, resolved, input_schemas, output_schemas, report)

    # ------------------------------------------------------------------ #
    # Stage 7 — policies & triage
    # ------------------------------------------------------------------ #
    async def _stage7_policies_triage(
        self, manifest: ProcessPackManifest, model: Optional[BpmnModel],
        report: ValidationReport, sample_envelopes: List[dict],
    ) -> None:
        policies = manifest.policies
        if policies and policies.separation_of_duties:
            for sod in policies.separation_of_duties:
                distinct = set(sod.elements)
                if len(distinct) < 2:
                    report.error("sod_too_few_elements", stage=7,
                                 message=f"SoD constraint needs >=2 distinct elements, got {sod.elements}")
                if model is not None:
                    for el in sod.elements:
                        if el not in model.tasks:
                            report.error("sod_unknown_element", stage=7, element_id=el,
                                         message=f"SoD element '{el}' is not a BPMN task")

        for rule in manifest.triage_rules:
            try:
                check_predicate(rule.when)
            except PredicateSyntaxError as exc:
                report.error("triage_rule_invalid", stage=7,
                             message=f"triage rule '{rule.rule_id}' predicate invalid: {exc}")
                continue
            for env in sample_envelopes:
                try:
                    matched = evaluate(rule.when, env)
                    report.info("triage_rule_smoke", stage=7,
                                message=f"rule '{rule.rule_id}' vs sample "
                                        f"'{env.get('exception_id', '?')}': {'MATCH' if matched else 'no match'}")
                except PredicateSyntaxError:
                    pass  # already reported by check_predicate
