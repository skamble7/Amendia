# app/engine/multi_instance.py
"""Multi-instance activities (ADR-036 / Backlog #3): run a bound task N times over a collection or a
cardinality, in **parallel** (a LangGraph ``Send`` fan-out) or **sequentially** (a guarded loop), and
aggregate the N per-iteration outputs back into one process artifact.

The core problem this solves: ``artifacts`` is a single last-wins ``merge_dicts`` channel keyed by
binding name, so N concurrent iterations writing the same output binding would clobber. So each
iteration writes into the index-scoped ``mi_results["{host}/{i}"]`` channel (never the bare binding),
and a **join** node reads those N results **in index order** and writes the final artifact — a list
(default) or ``{binding}#i`` indexed keys — validated against the pinned output schema exactly like any
capability output. Aggregation is by iteration index, so parallel and sequential are byte-identical.

MI on a task/activity only; MI on a sub-process, nested MI, and unbounded MI are refused by the shared
``compilability`` gate. HITL-gated MI and per-iteration error boundaries are deferred (the compiler
refuses a gated MI host); iterations run autonomously in ``execute`` mode.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from amendia_bpmn import MultiInstance
from app.engine import expr
from app.engine.executor import ExecutionContext, Executor
from app.engine.state import actor_entry
from app.engine.task_runner import NodeContext, NodeExecutionError, _map_and_validate


def mi_node_ids(host: str) -> Tuple[str, str]:
    """The derived iteration + join node ids for a parallel MI host (the host id stays the entry/
    dispatch node so incoming flows resolve to it unchanged). ``:`` / ``|`` are reserved by LangGraph
    for node names, so the suffix uses ``__``."""
    return f"{host}__mi_iter", f"{host}__mi_join"


def _cap_id(ctx: NodeContext) -> str:
    return ctx.descriptor.capability_id if ctx.descriptor else ctx.element_id


def _resolve_cardinality(mi: MultiInstance, artifacts: Dict[str, Any]) -> Tuple[int, Optional[List[Any]]]:
    """Determine N (and the per-iteration items, if a collection). Collection wins over cardinality
    when both are present (the collection is the data-driven source of truth)."""
    if mi.collection_ref:
        coll = artifacts.get(mi.collection_ref)
        if not isinstance(coll, list):
            raise NodeExecutionError(
                f"{mi.attached_to}: multi-instance collection '{mi.collection_ref}' is not a list "
                f"(got {type(coll).__name__})", reason="mi_collection_invalid")
        return len(coll), coll
    if mi.cardinality is not None:
        return int(mi.cardinality), None
    # Unbounded — refused at compilability; defensive fail-closed here.
    raise NodeExecutionError(
        f"{mi.attached_to}: multi-instance has neither cardinality nor collection", reason="mi_unbounded")


def _gather_inputs(ctx: NodeContext, artifacts: Dict[str, Any], mi: MultiInstance, item: Any) -> Dict[str, Any]:
    """Gather the iteration's inputs: the binding's declared inputs from state, with the per-item
    variable (``item_name``) injected as the collection element rather than read from state."""
    inputs: Dict[str, Any] = {}
    for spec in ctx.inputs:
        if mi.item_name and spec.name == mi.item_name:
            inputs[spec.name] = item
            continue
        if spec.name not in artifacts:
            raise NodeExecutionError(
                f"{ctx.element_id}: missing required input '{spec.name}' for a multi-instance iteration",
                reason="mi_missing_input")
        inputs[spec.name] = artifacts[spec.name]
    # item_name may be a fresh per-item variable not among the declared inputs — inject it too.
    if mi.item_name and mi.item_name not in inputs and item is not None:
        inputs[mi.item_name] = item
    return inputs


def _run_one(ctx: NodeContext, executor: Executor, simulation: bool, envelope: Dict[str, Any],
             artifacts: Dict[str, Any], mi: MultiInstance, index: int, item: Any,
             pid: Optional[str]) -> Dict[str, Any]:
    """Execute one iteration and return its produced outputs (keyed by artifact_key)."""
    inputs = _gather_inputs(ctx, artifacts, mi, item)
    exec_ctx = ExecutionContext(
        envelope=envelope, mode="execute", approved_action_ids=None, simulation=simulation,
        extras={
            "output_schemas": {s.artifact_key: s.json_schema for s in ctx.outputs},
            "element_id": ctx.element_id,
            "process_instance_id": pid,
            "memo_attempt": 0,
            "error_codes": [],
            # ADR-036: the iteration index + item, so a capability (or a test executor) can vary its
            # output per iteration even in the cardinality-only case (no collection item).
            "mi_index": index,
            "mi_item": item,
        },
    )
    result = executor.execute(ctx.descriptor, inputs, exec_ctx)
    return result.get("outputs", {}) or {}


def _aggregate(ctx: NodeContext, committed: List[Dict[str, Any]], aggregation: str) -> Dict[str, Any]:
    """Aggregate N validated per-iteration commits into the final artifact(s). ``list`` (default):
    one list artifact per binding output; ``indexed``: per-index scoped ``{binding}#i`` keys."""
    final: Dict[str, Any] = {}
    for spec in ctx.outputs:
        if aggregation == "indexed":
            for i, c in enumerate(committed):
                final[f"{spec.name}#{i}"] = c[spec.name]
        else:
            final[spec.name] = [c[spec.name] for c in committed]
    return final


def _validate_iteration(ctx: NodeContext, host: str, index: int, produced: Dict[str, Any]) -> Dict[str, Any]:
    committed, err = _map_and_validate(ctx, produced)
    if err is not None:
        raise NodeExecutionError(f"{host}: multi-instance iteration {index}: {err}", reason="schema_invalid")
    return committed


# --------------------------------------------------------------------------- #
# Parallel MI — Send fan-out → iteration node → join barrier
# --------------------------------------------------------------------------- #
def make_mi_dispatch_node(host: str) -> Callable:
    """The MI host entry node: pure passthrough; the conditional edge fans out the iterations."""
    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        return {}
    node.__name__ = f"mi_dispatch_{host}"
    return node


def make_mi_fan_out(host: str, mi: MultiInstance) -> Callable:
    """Routing function for the host's conditional edge: emit one ``Send`` per iteration to the
    iteration node, each carrying its index + item + the envelope/artifacts it needs. When N == 0 the
    iteration node never runs, so route straight to the join (which aggregates to an empty artifact)."""
    iter_id, join_id = mi_node_ids(host)

    def fan_out(state: Dict[str, Any]):
        artifacts = state.get("artifacts", {}) or {}
        n, items = _resolve_cardinality(mi, artifacts)
        if n <= 0:
            return [Send(join_id, {})]
        env = state.get("envelope", {})
        return [
            Send(iter_id, {"envelope": env, "artifacts": artifacts,
                           "__mi__": {"index": i, "item": (items[i] if items is not None else None)}})
            for i in range(n)
        ]
    return fan_out


def make_mi_iteration_node(ctx: NodeContext, executor: Executor, *, simulation: bool,
                           host: str, mi: MultiInstance) -> Callable:
    """One parallel iteration: reads its ``Send`` payload (index/item + envelope/artifacts), runs the
    capability, and writes the index-scoped result into ``mi_results`` (never the bare binding)."""
    def node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        pid = ((config or {}).get("configurable") or {}).get("thread_id")
        idx = state["__mi__"]["index"]
        item = state["__mi__"].get("item")
        produced = _run_one(ctx, executor, simulation, state.get("envelope", {}),
                            state.get("artifacts", {}) or {}, mi, idx, item, pid)
        return {
            "mi_results": {f"{host}/{idx}": produced},
            "actor_log": [actor_entry(host, _cap_id(ctx), "capability", meta={"mi_index": idx})],
        }
    node.__name__ = f"mi_iter_{host}"
    return node


def make_mi_join_node(ctx: NodeContext, *, host: str, mi: MultiInstance) -> Callable:
    """The join barrier (runs once after all iterations): reads the index-scoped ``mi_results`` in
    index order, validates each against the pinned output schema, and writes the aggregated final
    artifact into ``artifacts`` under the binding name(s). Downstream consumes it unchanged."""
    def node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        res = state.get("mi_results", {}) or {}
        prefix = f"{host}/"
        idxs = sorted(int(k[len(prefix):]) for k in res if k.startswith(prefix))
        committed = [_validate_iteration(ctx, host, i, res[f"{host}/{i}"]) for i in idxs]
        return {"artifacts": _aggregate(ctx, committed, mi.aggregation)}
    node.__name__ = f"mi_join_{host}"
    return node


# --------------------------------------------------------------------------- #
# Sequential MI — one guarded loop node (completionCondition early-exit)
# --------------------------------------------------------------------------- #
def make_sequential_mi_node(ctx: NodeContext, executor: Executor, *, simulation: bool,
                            host: str, mi: MultiInstance) -> Callable:
    """A sequential MI: iterate 0..N-1 in order, evaluating ``completionCondition`` after each
    iteration for an early exit, with the same index-scoped validation + index-ordered aggregation as
    the parallel path (so both produce identical artifacts for identical inputs)."""
    def node(state: Dict[str, Any], config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
        pid = ((config or {}).get("configurable") or {}).get("thread_id")
        envelope = state.get("envelope", {})
        artifacts = state.get("artifacts", {}) or {}
        n, items = _resolve_cardinality(mi, artifacts)
        committed: List[Dict[str, Any]] = []
        log: List[Dict[str, Any]] = []
        scratch: Dict[str, Any] = {}
        for i in range(n):
            item = items[i] if items is not None else None
            produced = _run_one(ctx, executor, simulation, envelope, artifacts, mi, i, item, pid)
            c = _validate_iteration(ctx, host, i, produced)
            committed.append(c)
            scratch[f"{host}/{i}"] = produced
            log.append(actor_entry(host, _cap_id(ctx), "capability", meta={"mi_index": i}))
            # completionCondition (sequential early-exit): evaluate against the artifacts overlaid with
            # THIS iteration's committed output, so a condition can branch on the iteration's own result.
            if mi.completion_condition and expr.evaluate(mi.completion_condition, {**artifacts, **c}):
                break
        return {
            "artifacts": _aggregate(ctx, committed, mi.aggregation),
            "mi_results": scratch,
            "actor_log": log,
        }
    node.__name__ = f"mi_seq_{host}"
    return node
