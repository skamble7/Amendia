# ADR-039 — Call activity: cross-pack composition (inline-compile)

**Status:** Accepted · **Date:** 2026-07-18 · **Builds on:** ADR-032 (embedded sub-process inline-flatten —
the model this extends, across packs), ADR-027/034 (execution profiles), ADR-024 (self-descriptive/pinnable
runtime). **Backlog:** ships Deferred-Backlog item **#1** (callActivity); records nested-instance execution,
MI-callee, and callActivity-boundary as new deferred stretches.

## Context

A `callActivity` invokes **another pack** as a reusable sub-process — cross-pack composition (a shared
"sanctions-rescreen" or "enrich-beneficiary" procedure reused by many packs). It was flatly refused
(`bpmn_call_activity_unsupported`) and didn't even capture its target. This is the biggest backlog item: a
contract + resolver problem, not a compiler tweak.

## Decision

**Inline-compile the callee.** At compile time, splice the *pinned* callee pack's compiled graph into the
caller's graph at the callActivity node — reusing the ADR-032 sub-process flatten. **One** process instance,
**one** checkpoint, **one** audit trail. Nested-instance execution (a child instance + parent↔child correlation
+ isolation) is **deferred** — a documented stretch.

Five moving parts:

1. **Target capture + the `call` executor kind.** The parser captures `callActivity/@calledElement` (the callee
   pack_key) + `amendia:calledVersion` (a semver range; absent → `DEFAULT_CALL_VERSION_RANGE = ^1.0.0`) into a
   `CallActivity` model entry. A `callActivity` binds a **new executor kind `call`**:
   `{type:"call", pack, version, input_map, output_map}` — the IO mapping (caller state → callee inputs;
   callee outputs → caller state) lives here, not in `binding.inputs/outputs`. It has no HITL of its own; the
   callee's own HITL/SoD run inline in the caller instance. `side_effect` is derived from the callee.

2. **Pinning at activation.** `resolve_pins` resolves each `callActivity`'s `pack@range` to the **active** callee
   `pack_key@version` (mirrors capability/artifact pinning; refused with `call_activity_pack_unresolved` if none
   active) and records it in `resolution.call_activities`. The instance then runs that pinned callee version
   reproducibly forever. The composite pack's **required profile is `max(caller, callee…)`**, pinned in the
   caller's resolution so the runtime's load-time profile guard still holds.

3. **Inline splice (the core).** A **`BundleProvider`** seam `(pack_key, version) → PackBundle` is injected into
   `compile_graph` (the engine pre-fetches the pinned callee bundles; the seed/test path resolves from
   `from_seed_dir`). At a callActivity the callee's graph is flattened in: **every callee node id and every
   callee binding name (state artifact key) is prefixed with the callActivity id** (`{ca}__{callee_id}`,
   mirroring multi-instance's `{host}/{i}` scoping — the `__` separator keeps scoped keys valid for `expr`), so
   a callee never collides with the caller. The flow into the callActivity → an **input-map** node (writes the
   callee inputs from `input_map` over caller state, scoped) → the callee's start-successor; the callee's
   end(s) → an **output-map** node (writes `output_map`: scoped callee outputs → caller artifacts) → the
   callActivity's parent outgoing target. This is a pure model transform (`app/engine/call_activity.py`), so
   `compile_graph`'s emission is reused unchanged and single-pack compilation stays byte-identical.

4. **Recursion / cycle + depth guards.** A callee that itself calls a pack is flattened first (recursion). A
   **cycle** (A→B→A) is refused (`bpmn_call_activity_cycle`); acyclic nesting is allowed but bounded by a
   **max-depth** (`bpmn_call_activity_depth`, default 5). Detected at both activation (registry static call
   graph) and compile.

5. **Profile + roles across the boundary.** `callActivity` **joins `common_executable`** —
   `bpmn_call_activity_unsupported` is retired from the always-refused set (now the profile-gate code, refused
   only under `common_subset`) and `required_profile` keys off call activities. Inline = one instance, so the
   callee's HITL tasks / SoD / roles run **in the caller instance** (callee pack-local roles surface there; SoD
   within the callee still holds). Cross-pack role *namespacing* beyond reuse-as-is is out of scope.

**Validation** (registry, `app/validation/call.py`, needs the pack repo): `bpmn_call_activity_no_target`,
`call_activity_pack_unresolved`, `call_activity_io_unmapped` (a callee required input has no `input_map` entry,
or `output_map` names an unknown callee output), `call_activity_io_mismatch` (a mapped caller source not
produced upstream — mirrors the gateway-variable rule), `bpmn_call_activity_cycle`, `bpmn_call_activity_depth`,
`call_activity_profile_exceeds`. A callActivity as a **multi-instance host** or carrying a **boundary event** is
refused (`bpmn_call_activity_multi_instance_unsupported` / the reused subprocess-boundary refusal).

## Consequences

- A `callActivity` invokes another pack, pinned at activation and inline-compiled into one instance/audit trail
  with explicit IO maps and namespace-scoped callee artifacts. Acyclic bounded-depth call graphs run; cycles,
  unresolved/unmapped/mismatched IO, MI-host, and boundary-on-callActivity are refused. The composite required
  profile is the max of caller+callee. Registry and runtime share the same guards, so they can't diverge.

## Deferred / non-goals (newly recorded)

- **Nested-instance execution** (child instance + parent↔child correlation + isolation) — the deferred stretch;
  inline-compile is this cut.
- **callActivity as a multi-instance host** (call-a-pack-N-times) and **boundary events on a callActivity** —
  deferred.
- No cross-pack **role namespacing** beyond reuse-as-is; no **dynamic** (runtime-chosen) callee (the pin is
  fixed at activation); no callActivity-level compensation.
