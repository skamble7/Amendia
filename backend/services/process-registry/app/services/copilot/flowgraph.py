# app/services/copilot/flowgraph.py
"""A directed BPMN sequence-flow graph for reachability / dominance queries (ADR-052).

Purely structural and domain-neutral: it knows only nodes and directed edges, nothing about tasks, gateways,
or business meaning. The copilot uses it to decide whether an artifact an element consumes is *guaranteed* to
exist by the time that element runs — a producer that only runs on a loop-back (after the consumer) or on a
subset of branches cannot guarantee its output, so the consuming field must be optional.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, Tuple


class FlowGraph:
    """Directed graph of BPMN sequence flows rooted at the start event."""

    def __init__(self, edges: Iterable[Tuple[str, str]], start: Optional[str]) -> None:
        self._succ: Dict[str, Set[str]] = {}
        self._nodes: Set[str] = set()
        for s, t in edges:
            if not s or not t:
                continue
            self._succ.setdefault(s, set()).add(t)
            self._nodes.update((s, t))
        self.start = start

    def _reach(self, src: str, skip: Optional[str] = None) -> Set[str]:
        """Nodes reachable from ``src`` along successor edges (``src`` itself is included only if a cycle
        returns to it). Never traverses through ``skip`` — used to test dominance by node removal."""
        seen: Set[str] = set()
        stack = [t for t in self._succ.get(src, ()) if t != skip]
        while stack:
            n = stack.pop()
            if n in seen or n == skip:
                continue
            seen.add(n)
            stack.extend(t for t in self._succ.get(n, ()) if t != skip)
        return seen

    def dominates(self, p: str, e: str) -> bool:
        """True iff every forward path from the start event to ``e`` passes through ``p`` (``p`` dominates ``e``).
        Computed structurally: with ``p`` removed from the graph, ``e`` is no longer reachable from start. The
        start event dominates everything (it is the root of every path)."""
        if self.start is None:
            return False
        if p == self.start or p == e:
            return True
        return e not in self._reach(self.start, skip=p)

    def can_reach(self, src: str, dst: str) -> bool:
        """True iff there's a forward path ``src → … → dst`` (used to detect a loop-back)."""
        return dst in self._reach(src)

    def guaranteed_predecessor(self, p: str, e: str) -> bool:
        """``p`` is a *guaranteed* predecessor of ``e``: it lies on every path from start to ``e`` (dominates)
        AND ``e`` has no forward path back to ``p`` (``p`` is strictly upstream, not a loop-back producer)."""
        if p == e:
            return True
        return self.dominates(p, e) and not self.can_reach(e, p)


def build_flow_graph(sem) -> Optional[FlowGraph]:
    """From a ``BpmnSemanticModel`` → a ``FlowGraph`` rooted at the first start event. ``None`` when the diagram
    carries no sequence flows (nothing to reason about)."""
    edges = [(f.source, f.target) for f in getattr(sem, "sequence_flows", []) if f.source and f.target]
    if not edges:
        return None
    start = next((n.id for n in getattr(sem, "flow_nodes", []) if n.kind == "startEvent"), None)
    return FlowGraph(edges, start)
