# app/validation/call.py
"""Registry validation for the `call` executor kind — cross-pack composition (ADR-039).

A ``callActivity`` binds another pack (the callee) that the runtime inline-compiles. These checks
refuse a caller that can't be composed at activation: an unresolvable/inactive callee, unmapped or
un-produced IO, and a cyclic or too-deep call graph — the same guards the compiler raises off, so
registry and runtime never diverge. All additive: a pack with no call binding is untouched.
"""
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from packaging.version import Version

from amendia_bpmn import BpmnModel, profile_rank
from amendia_contracts.process_pack import ProcessPackManifest
from amendia_contracts.semver import satisfies
from app.validation.report import ValidationReport

MAX_CALL_DEPTH = 5  # mirrors app/engine/call_activity.py::DEFAULT_MAX_CALL_DEPTH


def _forward_reach(model: BpmnModel) -> Dict[str, Set[str]]:
    adj: Dict[str, List[str]] = {n: [] for n in model.node_ids}
    for f in model.flows:
        if f.source in adj and f.target in adj:
            adj[f.source].append(f.target)
    reach: Dict[str, Set[str]] = {}
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


async def _active_pin(pack_repo: Any, pack_key: str, spec: str):
    active = [m for m in await pack_repo.list_versions(pack_key)
              if m.status.value == "active" and satisfies(m.version, spec)]
    if not active:
        return None
    return max(active, key=lambda m: Version(m.version))


def _callee_io(callee: ProcessPackManifest) -> Tuple[Set[str], Set[str]]:
    """The callee's required inputs (binding inputs not produced by any binding output — the seed
    inputs the caller must supply) and its available outputs (all binding output names)."""
    inputs = {io.name for b in callee.bindings for io in b.inputs}
    outputs = {io.name for b in callee.bindings for io in b.outputs}
    return inputs - outputs, outputs


async def _walk_call_graph(pack_repo: Any, mf: ProcessPackManifest,
                           stack: Tuple[str, ...], depth: int, report: ValidationReport,
                           reported: Set[str]) -> None:
    """DFS the static cross-pack call graph from ``mf`` (the caller manifest, then each active callee);
    report a cycle or excess depth once."""
    for b in mf.bindings:
        if getattr(b.executor, "type", None) != "call":
            continue
        callee = b.executor.pack
        if callee in stack:
            key = "cycle:" + "->".join(stack + (callee,))
            if key not in reported:
                reported.add(key)
                report.error("bpmn_call_activity_cycle", stage=1, element_id=b.element_id,
                             message=f"callActivity cycle: {' -> '.join(stack + (callee,))}")
            continue
        if depth + 1 > MAX_CALL_DEPTH:
            if "depth" not in reported:
                reported.add("depth")
                report.error("bpmn_call_activity_depth", stage=1, element_id=b.element_id,
                             message=f"callActivity nesting exceeds max depth {MAX_CALL_DEPTH}")
            continue
        pinned = await _active_pin(pack_repo, callee, b.executor.version)
        if pinned is None:
            continue  # unresolved is reported by the per-binding check
        await _walk_call_graph(pack_repo, pinned, stack + (callee,), depth + 1, report, reported)


async def validate_call_bindings(
    manifest: ProcessPackManifest, model: BpmnModel, pack_repo: Any, report: ValidationReport,
) -> None:
    """Validate every ``call`` binding (ADR-039). No-op if the pack has no call binding or no pack repo."""
    call_bindings = [b for b in manifest.bindings if getattr(b.executor, "type", None) == "call"]
    if not call_bindings or pack_repo is None:
        return

    reach = _forward_reach(model)
    producers: Dict[str, List[str]] = {}
    for b in manifest.bindings:
        for io in b.outputs:
            producers.setdefault(io.name, []).append(b.element_id)

    reported: Set[str] = set()
    for b in call_bindings:
        el, ex = b.element_id, b.executor
        pinned = await _active_pin(pack_repo, ex.pack, ex.version)
        if pinned is None:
            report.error("call_activity_pack_unresolved", stage=3, element_id=el,
                         message=f"callActivity '{el}': callee pack '{ex.pack}@{ex.version}' has no "
                                 f"active version satisfying the range")
            continue

        # composite profile: the callee must not require a profile beyond common_executable.
        callee_res = await pack_repo.get_resolution(ex.pack, pinned.version) or {}
        callee_prof = callee_res.get("required_execution_profile", "common_subset")
        if profile_rank(callee_prof) > profile_rank("common_executable"):
            report.error("call_activity_profile_exceeds", stage=1, element_id=el,
                         message=f"callActivity '{el}': callee requires profile '{callee_prof}' beyond "
                                 f"the executable ceiling")

        # IO mapping — required callee inputs mapped; output_map names real callee outputs.
        required_inputs, callee_outputs = _callee_io(pinned)
        for need in sorted(required_inputs - set(ex.input_map)):
            report.error("call_activity_io_unmapped", stage=5, element_id=el,
                         message=f"callActivity '{el}': callee required input '{need}' has no input_map entry")
        for bad in sorted(set(ex.input_map) - {io.name for bb in pinned.bindings for io in bb.inputs}):
            report.error("call_activity_io_unmapped", stage=5, element_id=el,
                         message=f"callActivity '{el}': input_map key '{bad}' is not a callee input")
        for caller_art, callee_out in ex.output_map.items():
            if callee_out not in callee_outputs:
                report.error("call_activity_io_unmapped", stage=5, element_id=el,
                             message=f"callActivity '{el}': output_map '{caller_art}' <- '{callee_out}' "
                                     f"names an unknown callee output")

        # IO source must be produced upstream in the caller (mirror the gateway-variable rule).
        for callee_in, caller_src in ex.input_map.items():
            root = caller_src.split(".")[0]
            if not any(el in reach.get(p, set()) for p in producers.get(root, [])):
                report.error("call_activity_io_mismatch", stage=5, element_id=el,
                             message=f"callActivity '{el}': input_map source '{caller_src}' (artifact "
                                     f"'{root}') is not produced by any binding upstream of the callActivity")

    # cycle / depth over the whole static call graph (from this caller, then each active callee).
    await _walk_call_graph(pack_repo, manifest, (manifest.pack_key,), 0, report, reported)
