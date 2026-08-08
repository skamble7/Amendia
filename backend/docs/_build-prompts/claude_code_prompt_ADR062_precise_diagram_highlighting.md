# Claude Code prompt — ADR-062: precise process-diagram highlighting for terminal instances

Implement **ADR-062** (`backend/docs/adr/ADR-062-precise-process-diagram-highlighting-for-terminal-instances.md`).
A small webui-only precision fix — confirm the behaviour against a real completed instance before and after.

## Goal

A terminal (completed / failed / cancelled) instance's BPMN diagram (and the context-rail step tracker) must
green **only the elements the instance actually executed**, leaving un-taken branches grey (`pending`) — instead
of greening every task. During execution the view is already precise; only the terminal case is wrong.

## Root cause (confirmed)

`webui/src/lib/steps.ts::deriveSteps` has a fallback that overrides the `actor_log`-derived "done":

```ts
else if (acted.has(element_id)) state = "done";
else if (terminal) state = "done"; // ← greens EVERY binding once terminal
```

`acted` is the set of `actor_log` element ids (what actually ran). The `terminal` branch discards that.

## Read first

- `webui/src/lib/steps.ts` — `deriveSteps` (the fix) and the `Step` type.
- `webui/src/features/task/useProcessProgress.ts` — computes `terminal` and calls `deriveSteps`.
- `webui/src/features/task/ProcessDiagramView.tsx` — maps `steps` → `BpmnMarker[]`.
- `webui/src/features/registry/BpmnViewer.tsx` — the marker → color mapping (done/current/pending/failed).
- Tests that pin the current behaviour: `webui/src/features/task/contextRailSteps.test.ts`,
  `webui/src/features/task/processDiagram.test.tsx`, and any `steps` test.
- `webui/src/api/types.ts` — `ActorLogEntry` shape (confirm `element_id` is the executed-element key).

## Tasks

1. **Remove the blanket terminal fallback** in `deriveSteps`: delete `else if (terminal) state = "done";` so
   `done` derives purely from `acted.has(element_id)` (with `failed` / `current` unchanged). Keep the `terminal`
   param in the signature only if still used elsewhere; otherwise remove it and its plumbing in
   `useProcessProgress.ts` (don't leave a dead param).
2. **Verify `actor_log` completeness (the ADR-062 guard).** Confirm against a **real completed instance** that
   every executed task is in `actor_log` — drive the wire happy path to `End_Resolved` and check the diagram
   greens exactly `Enrich, Assess, DraftRepair, ApproveRepair, Screen, ApplyRepair, Notify, Record` and leaves
   `DraftReturn, ApproveReturn, ExecuteReturn, ObtainInfo, Escalate` grey. If a genuinely-executed task is absent
   from `actor_log`, do **not** restore the blanket fallback — instead broaden `done` to also include elements
   that produced a committed artifact (thread that set in from the instance state), and note it in the report.
3. **Update tests** to the precise semantics: a terminal instance marks done = `actor_log` elements only;
   un-taken bindings are `pending` (add/adjust a test asserting a not-acted binding is `pending` on a completed
   instance, and that a failed instance shows failed-node red + executed-path green + rest pending).
4. Confirm the **context rail** (same `deriveSteps`) reads correctly for a completed instance — executed steps
   done, un-taken steps pending — and that nothing else depended on the old "all done" behaviour.

## Do not

- No backend / engine / `actor_log` changes; gateways and end-events are not bindings and stay as-is.
- Don't restore a blanket "terminal → all done" in any form.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A completed instance's diagram + context rail green only the executed path; un-taken branches are grey. A
  failed instance shows the failed node red, the path to it green, the rest grey.
- During execution, behaviour is unchanged (still precise, open gate purple).
- `npm run typecheck` + webui tests green; the updated tests assert the precise terminal semantics; no dead
  `terminal` param left behind.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR062_precise_diagram_highlighting_report.md`
(uncommitted): (1) outcome one-liner; (2) the `deriveSteps` change + whether `terminal` was removed or kept and
why; (3) the actor_log-completeness verification result (the wire happy-path check — which nodes green vs grey),
and whether the committed-artifact broadening was needed; (4) tests updated; (5) verification commands + results;
(6) anything left open. Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Stay inside `webui/` (unless the actor_log-broadening
guard requires reading instance state that's already exposed) and the scope above.
