# app/validation/pack_validator.py
"""Cross-contract pack validation pipeline (the heart of the registry).

Seven ordered stages (contracts doc validation matrix / reference §9), each appending
findings to a single ValidationReport. Later stages emit ``stage_skipped`` when a hard
prerequisite (a parseable BPMN) is missing. Deterministic output.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from packaging.version import Version

from amendia_contracts.capability import CapabilityDescriptor
from amendia_contracts.common import HitlMode, hitl_mode_at_least
from amendia_contracts.process_pack import ProcessPackManifest
from app.validation.deep_agent import validate_deep_agent_bindings
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
    def __init__(self, cap_repo: CapabilityRepository, schema_repo: ArtifactSchemaRepository) -> None:
        self.caps = cap_repo
        self.schemas = schema_repo

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
        return parse_and_validate(
            bpmn_xml,
            expected_process_id=manifest.process.process_id,
            expected_sha256=manifest.process.bpmn_sha256,
            report=report,
        )

    # ------------------------------------------------------------------ #
    # Stage 2 — binding ↔ task bijection
    # ------------------------------------------------------------------ #
    def _stage2_bijection(self, manifest: ProcessPackManifest, model: BpmnModel, report: ValidationReport) -> None:
        binding_ids = [b.element_id for b in manifest.bindings]
        seen = set()
        for b in manifest.bindings:
            if b.element_id in seen:
                report.error("duplicate_binding", stage=2, element_id=b.element_id,
                             message=f"more than one binding for element '{b.element_id}'")
            seen.add(b.element_id)
            kind = model.tasks.get(b.element_id)
            if kind is None:
                report.error("orphan_binding", stage=2, element_id=b.element_id,
                             message=f"binding references '{b.element_id}' which is not a BPMN service/user task")
                continue
            if kind != b.element_kind:
                report.error("binding_kind_mismatch", stage=2, element_id=b.element_id,
                             message=f"binding element_kind '{b.element_kind}' != BPMN kind '{kind}'")
            etype = b.executor.type
            if kind == "serviceTask" and etype != "capability":
                report.error("executor_kind_mismatch", stage=2, element_id=b.element_id,
                             message="serviceTask must bind a capability executor")
            if kind == "userTask" and etype != "human":
                report.error("executor_kind_mismatch", stage=2, element_id=b.element_id,
                             message="userTask must bind a human executor")
        for task_id in sorted(set(model.tasks) - set(binding_ids)):
            report.error("unbound_task", stage=2, element_id=task_id,
                         message=f"BPMN task '{task_id}' has no binding")

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
