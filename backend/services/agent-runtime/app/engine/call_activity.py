# app/engine/call_activity.py
"""Cross-pack composition via inline-compile (ADR-039).

A ``callActivity`` invokes **another pack** as a reusable sub-process. At compile time we splice the
*pinned* callee pack's graph into the caller's graph at the callActivity node — one process instance,
one checkpoint, one audit trail (extends the ADR-032 sub-process flatten, across packs). Nested-instance
execution (a child instance + parent↔child correlation) is deferred.

Mechanism (a pure model transform, so ``compile_graph``'s emission is reused almost unchanged):
  * every callee node id and every callee **binding name** (state artifact key) is prefixed with the
    callActivity id (``{ca}__{callee_id}``) — mirroring multi-instance's ``{host}/{i}`` scoping — so a
    callee never collides with the caller (the ``__`` separator keeps scoped keys valid for ``expr``);
  * the flow into the callActivity → an **input-map** node (writes the callee's input artifacts from
    ``input_map`` over caller state, into the scoped namespace) → the callee's start-successor;
  * the callee's end(s) → an **output-map** node (writes ``output_map``: scoped callee outputs → caller
    artifacts) → the callActivity's parent outgoing target;
  * a callee that itself calls a pack is flattened first (recursion), with a **cycle** guard (A→B→A) and
    a **max-depth** guard.

``compile_graph`` calls :func:`flatten_call_activities`; for a pack with no callActivity it returns the
identity ``(model, build_node_contexts(bundle), {})`` — so single-pack compilation is byte-unchanged.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, replace as dc_replace
from typing import Any, Callable, Dict, Optional, Tuple

from amendia_bpmn import BpmnModel
from amendia_bpmn.model import Flow

from app.engine import expr
from app.engine.bundle import PackBundle, build_node_contexts
from app.engine.state import actor_entry
from app.engine.task_runner import IOSpec, NodeContext, OutputSpec

# A caller loads the pinned callee PackBundle through this seam (registry client / seed loader).
BundleProvider = Callable[[str, str], PackBundle]

SEP = "__"                      # scope separator (expr-safe: [A-Za-z0-9_])
DEFAULT_MAX_CALL_DEPTH = 5      # bounded finite depth; deeper acyclic nesting is refused (ADR-039)


class CallActivityError(Exception):
    """A callActivity cannot be inline-compiled (no target, cycle, depth, unresolved callee)."""


@dataclass
class MapNode:
    """A boundary state-copy node spliced at a callActivity (input-map or output-map)."""

    element_id: str
    kind: str                       # "in" | "out"
    mapping: Dict[str, str]         # in: scoped_callee_input -> caller_dotpath ; out: caller_artifact -> scoped_callee_output
    call_element: str               # the callActivity id (audit)
    callee_pack: str


# --------------------------------------------------------------------------- #
# Scoping helpers (prefix every id / binding name so a callee never collides)
# --------------------------------------------------------------------------- #
def _scope_path(prefix: str, dotpath: str) -> str:
    """Prefix the ROOT segment of a dotpath (an artifact/binding name); a single-segment name is just
    prefixed whole. Keeps ``expr`` dotpaths valid (``{prefix}root.rest``)."""
    root, _, rest = dotpath.partition(".")
    return f"{prefix}{root}" + (f".{rest}" if rest else "")


def _scope_condition(prefix: str, cond: Optional[str]) -> Optional[str]:
    """Prefix the leading identifier (the artifact root) of a gateway flow condition."""
    if not cond:
        return cond
    return re.sub(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)",
                  lambda m: f"{m.group(1)}{prefix}{m.group(2)}", cond, count=1)


def _scope_flow(prefix: str, f: Flow) -> Flow:
    return Flow(id=f"{prefix}{f.id}", source=f"{prefix}{f.source}", target=f"{prefix}{f.target}",
                has_condition=f.has_condition, condition_expr=_scope_condition(prefix, f.condition_expr),
                name=f.name)


def _scope_ctx(prefix: str, ctx: NodeContext) -> NodeContext:
    """Scope a callee NodeContext: the element id + every binding NAME (the state artifact key), so
    callee tasks read/write the scoped namespace. The pinned artifact_key + descriptor stay (the
    capability still produces its own artifact_key; only the *state* key is scoped)."""
    return NodeContext(
        element_id=f"{prefix}{ctx.element_id}",
        element_kind=ctx.element_kind, hitl_mode=ctx.hitl_mode, role=ctx.role,
        executor_type=ctx.executor_type, descriptor=ctx.descriptor,
        assist_descriptor=ctx.assist_descriptor,
        inputs=[IOSpec(name=f"{prefix}{io.name}", schema_ref=io.schema_ref) for io in ctx.inputs],
        outputs=[OutputSpec(name=f"{prefix}{o.name}", artifact_key=o.artifact_key,
                            schema_ref=o.schema_ref, json_schema=o.json_schema) for o in ctx.outputs],
        title=ctx.title, message_name=ctx.message_name, error_codes=list(ctx.error_codes),
    )


def _scope_map_node(prefix: str, m: MapNode) -> MapNode:
    return MapNode(
        element_id=f"{prefix}{m.element_id}", kind=m.kind,
        mapping={_scope_path(prefix, k): _scope_path(prefix, v) for k, v in m.mapping.items()},
        call_element=f"{prefix}{m.call_element}", callee_pack=m.callee_pack)


def _scope_model(prefix: str, model: BpmnModel) -> BpmnModel:
    """A scoped copy of a (already-flattened) callee model — every node id / flow / condition prefixed.
    Only the top-level flat constructs are scoped (a flattened callee has no nested subprocess/call);
    beyond-subset constructs a callee uses (error boundaries, multi-instance) are scoped defensively."""
    def s(x: str) -> str:
        return f"{prefix}{x}"

    m = BpmnModel(process_id=s(model.process_id))
    m.tasks = {s(t): k for t, k in model.tasks.items()}
    m.exclusive_gateways = [s(g) for g in model.exclusive_gateways]
    m.parallel_gateways = [s(g) for g in model.parallel_gateways]
    m.node_ids = {s(n) for n in model.node_ids}
    m.flows = [_scope_flow(prefix, f) for f in model.flows]
    m.exclusive_conditions = {s(g): [s(fid) for fid in fids] for g, fids in model.exclusive_conditions.items()}
    m.start_events = [s(e) for e in model.start_events]
    m.end_events = [s(e) for e in model.end_events]
    m.gateway_defaults = {s(g): s(fid) for g, fid in model.gateway_defaults.items()}
    # Defensive scoping of beyond-subset constructs a callee might use internally.
    m.error_boundaries = {
        s(host): [dc_replace(eb, id=s(eb.id), attached_to=s(eb.attached_to), target=s(eb.target))
                  for eb in ebs]
        for host, ebs in model.error_boundaries.items()
    } if model.error_boundaries else {}
    m.multi_instance = {
        s(host): dc_replace(mi, attached_to=s(mi.attached_to)) for host, mi in model.multi_instance.items()
    } if model.multi_instance else {}
    return m


# --------------------------------------------------------------------------- #
# Flatten (recursive) + splice
# --------------------------------------------------------------------------- #
def flatten_call_activities(
    bundle: PackBundle, provider: Optional[BundleProvider], *,
    call_stack: Tuple[str, ...] = (), depth: int = 0, max_depth: int = DEFAULT_MAX_CALL_DEPTH,
) -> Tuple[BpmnModel, Dict[str, NodeContext], Dict[str, MapNode]]:
    """Return ``(model, node_ctxs, boundary_maps)`` with every callActivity inline-spliced. For a pack
    with no callActivity this is the identity — single-pack compilation is byte-unchanged."""
    model = bundle.bpmn_model
    node_ctxs = build_node_contexts(bundle)
    if not model.call_activities:
        return model, node_ctxs, {}
    if provider is None:
        raise CallActivityError(
            f"pack '{bundle.pack_key}' has callActivities but no bundle provider was supplied")

    stack = call_stack or (bundle.pack_key,)
    merged = copy.deepcopy(model)
    merged_ctxs = dict(node_ctxs)
    maps: Dict[str, MapNode] = {}
    call_bindings = {b.element_id: b for b in bundle.manifest.bindings
                     if getattr(b.executor, "type", None) == "call"}

    for ca_id, ca in model.call_activities.items():
        binding = call_bindings.get(ca_id)
        target = (binding.executor.pack if binding else None) or ca.target_pack
        if not target:
            raise CallActivityError(f"callActivity '{ca_id}' has no target pack")
        if target in stack:
            raise CallActivityError(
                f"call_activity_cycle: {' -> '.join(stack + (target,))}")
        if depth + 1 > max_depth:
            raise CallActivityError(
                f"call_activity_depth: exceeds max depth {max_depth} at callActivity '{ca_id}'")
        version = _pinned_callee_version(bundle, ca_id) or (binding.executor.version if binding else ca.version_range)
        callee = provider(target, version)
        cmodel, cctxs, cmaps = flatten_call_activities(
            callee, provider, call_stack=stack + (target,), depth=depth + 1, max_depth=max_depth)
        input_map = dict(binding.executor.input_map) if binding else {}
        output_map = dict(binding.executor.output_map) if binding else {}
        _splice(merged, merged_ctxs, maps, ca_id, target,
                cmodel, cctxs, cmaps, input_map, output_map)

    return merged, merged_ctxs, maps


def _pinned_callee_version(bundle: PackBundle, ca_id: str) -> Optional[str]:
    """The callee version pinned at activation (production resolution sidecar); ``None`` for a seed
    bundle (which resolves the callee by pack_key)."""
    for entry in bundle.resolution.get("call_activities", []) or []:
        if entry.get("element") == ca_id:
            return entry.get("version")
    return None


def _splice(merged: BpmnModel, merged_ctxs: Dict[str, NodeContext], maps: Dict[str, MapNode],
            ca_id: str, callee_pack: str, cmodel: BpmnModel, cctxs: Dict[str, NodeContext],
            cmaps: Dict[str, MapNode], input_map: Dict[str, str], output_map: Dict[str, str]) -> None:
    """Splice the (already-flattened) callee into ``merged`` at callActivity ``ca_id``."""
    prefix = f"{ca_id}{SEP}"
    smodel = _scope_model(prefix, cmodel)

    # Scoped callee node contexts + nested boundary maps.
    for cctx in cctxs.values():
        sc = _scope_ctx(prefix, cctx)
        merged_ctxs[sc.element_id] = sc
    for mnode in cmaps.values():
        sm = _scope_map_node(prefix, mnode)
        maps[sm.element_id] = sm

    # The input/output boundary map nodes.
    in_id, out_id = f"{prefix}in", f"{prefix}out"
    maps[in_id] = MapNode(in_id, "in", {f"{prefix}{k}": v for k, v in input_map.items()}, ca_id, callee_pack)
    maps[out_id] = MapNode(out_id, "out", {k: f"{prefix}{v}" for k, v in output_map.items()}, ca_id, callee_pack)

    # Merge scoped callee nodes (tasks + gateways) — NOT its start/end events (they become edges).
    callee_start = smodel.start_events[0]
    callee_ends = set(smodel.end_events)
    merged.tasks.update(smodel.tasks)
    merged.exclusive_gateways.extend(smodel.exclusive_gateways)
    merged.parallel_gateways.extend(smodel.parallel_gateways)
    merged.gateway_defaults.update(smodel.gateway_defaults)
    merged.exclusive_conditions.update(smodel.exclusive_conditions)
    if smodel.error_boundaries:
        merged.error_boundaries.update(smodel.error_boundaries)
    if smodel.multi_instance:
        merged.multi_instance.update(smodel.multi_instance)
    merged.node_ids |= (smodel.node_ids - {callee_start} - callee_ends)

    entry = next(f.target for f in smodel.flows if f.source == callee_start)  # callee start-successor

    # Rewire the caller's edges to/from the callActivity through the boundary map nodes.
    for f in merged.flows:
        if f.target == ca_id:
            f.target = in_id
        if f.source == ca_id:
            f.source = out_id
    # Add scoped callee flows: drop the start's outgoing (replaced by in-node → entry); a flow into a
    # callee end becomes a flow into the out-node; everything else carries over.
    for f in smodel.flows:
        if f.source == callee_start:
            continue
        if f.target in callee_ends:
            merged.flows.append(Flow(id=f.id, source=f.source, target=out_id,
                                     has_condition=f.has_condition, condition_expr=f.condition_expr, name=f.name))
        else:
            merged.flows.append(f)
    merged.flows.append(Flow(id=f"{prefix}__in_flow", source=in_id, target=entry, has_condition=False))

    # Retire the callActivity placeholder.
    merged.call_activities.pop(ca_id, None)
    merged.node_ids.discard(ca_id)
    merged_ctxs.pop(ca_id, None)


# --------------------------------------------------------------------------- #
# Boundary map node factory (compiled into the graph)
# --------------------------------------------------------------------------- #
def make_map_node(m: MapNode) -> Callable:
    """A pure state-copy node at a callActivity boundary. ``in``: write each scoped callee input from a
    caller-state dotpath. ``out``: write each caller artifact from a scoped callee output. Emits one
    ``actor_log`` entry (kind ``call``) so the single instance's audit trail carries the composition."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        arts = state.get("artifacts", {}) or {}
        delta: Dict[str, Any] = {}
        for dest, src in m.mapping.items():
            delta[dest] = expr.resolve_path(src.split("."), arts)
        return {
            "artifacts": delta,
            "actor_log": [actor_entry(m.call_element, f"call:{m.callee_pack}", "call",
                                      meta={"map": m.kind})],
        }
    node.__name__ = f"callmap_{m.element_id}"
    return node
