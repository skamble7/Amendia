# ADR-062 — Precise process-diagram highlighting for terminal instances (only the executed path)

**Status:** Proposed — 2026-08-08
**Date:** 2026-08-08
**Context owner:** Sandeep Kamble
**Relates:** the webui task/instance process-diagram (`ProcessDiagramView`, `BpmnViewer`, `lib/steps.ts`
`deriveSteps`), the instance `actor_log`.

## Context

The task/instance BPMN view paints per-element execution state (done / current / pending / failed) over the
pack's diagram. **While an instance runs, it is precise** — only the actually-visited elements are green, the
open gate is purple, the rest grey. **But once the instance reaches a terminal state** (completed / failed /
cancelled), the diagram paints **every** task green — including branches the instance never took (e.g. a
repair-path completion still greens `DraftReturn` / `ApproveReturn` / `ExecuteReturn` / `ObtainInfo` /
`Escalate`). That misrepresents what happened: a viewer can no longer tell which path the instance actually ran.

Root cause is a single fallback in `webui/src/lib/steps.ts::deriveSteps`:

```ts
else if (acted.has(element_id)) state = "done";
else if (terminal) state = "done"; // ← greens EVERY binding once the instance is terminal
```

`acted` is the set of element ids in the instance's `actor_log` (the elements that actually executed). The
`terminal` fallback overrides that and marks *all* bindings done, discarding the executed-path information the
`actor_log` already carries.

## Decision

**A terminal instance's diagram shows done = only the elements it actually executed; un-taken branches stay
`pending`.** Concretely: remove the `else if (terminal) state = "done"` fallback so "done" derives purely from
`actor_log` membership (plus `failed`/`current` as today). A completed instance thus greens exactly its executed
path and leaves the branches it never entered grey — a precise depiction.

- `done` = element id present in `actor_log` (it executed).
- `failed` = the failed element (unchanged).
- `current` = the open/claimed HITL element (naturally absent on a terminal instance).
- everything else = `pending` (not executed) — including on completion.

**Correctness guard:** this is only precise if `actor_log` contains *every* executed task. Each capability
commit and human decision appends an `actor_log` entry, and `deriveSteps` maps over task **bindings** only
(gateways/end-events aren't bindings and were never marked), so a completed instance's executed tasks are all
logged. The implementation must **verify** this against a real completed instance (the wire happy path:
`Enrich, Assess, DraftRepair, ApproveRepair, Screen, ApplyRepair, Notify, Record` green; the return/hold/escalate
tasks grey). If any executed task is legitimately absent from `actor_log`, broaden `done` to also include
elements that produced a committed artifact — rather than resurrecting the blanket `terminal` fallback.

## Consequences

- The completed/failed diagram (and the shared context-rail step tracker, which uses the same `deriveSteps`)
  become path-precise: viewers see exactly which activities ran. This is the intended governance/audit value of
  the diagram — an accurate record, not a "everything lit up" summary.
- Failed instances also improve: the failed node is red, the path up to it is green, the rest grey — instead of
  a mostly-green diagram with one red node.
- One-line behavioural change with a test flip: the existing "terminal → all done" expectation (if any) is
  replaced by "terminal → only actor_log elements done, un-taken branches pending."

## Scope boundaries

Backend, the engine, `actor_log` content, and gateway/end-event rendering are unchanged. This is a
presentation-layer precision fix in the webui only.
