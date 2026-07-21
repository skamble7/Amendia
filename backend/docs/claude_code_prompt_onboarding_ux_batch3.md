# Claude Code Prompt — Onboarding wizard UX refinements (batch 3): fix the assemble 500 on an unbound capability

From operator testing: running the wizard through to **Review & activate** and pressing validate/assemble
returned a raw **500 Internal Server Error** ("Internal Server Error" toast). The process-registry traceback is:

```
POST /onboarding/onb-…/assemble → 500
  onboarding.py:533  assemble → self._compose(s)
  onboarding.py:1042 _compose → ProcessPackManifest.model_validate({...})
  amendia_contracts/common.py:151 VersionedRef._validate → :133 parse
  TypeError: VersionedRef must be a string, got NoneType
```

## Root cause (confirmed by code read — no guessing needed)

A **capability** binding was saved with `capability_ref = None` — i.e. a capability/`businessRuleTask` element
whose **Capability** dropdown was left `Select…` (batch-2 pre-fill found no confident match, or the operator
never picked one; the most likely culprit in the wire-repair pack is the `Assess`/`businessRuleTask` decision
that was not authored, so no staged capability existed to pre-select).

Two gaps let a `None` ref reach manifest validation as a raw 500 instead of a clean, actionable error:

1. **`set_bindings` (onboarding.py ~408) never requires the ref.** The IO/policy validation is gated on
   truthiness:
   ```python
   if b.executor_type == "capability" and b.capability_ref:   # ← None slips straight past
       cap_io = await self._capability_io_and_policy(b.capability_ref, s)
       ...
   ```
   So a capability binding with `capability_ref = None` produces **no error**, is saved via `StagedBinding(...,
   capability_ref=None, ...)`, and advances the state. Note the bijection check (~446) only catches elements with
   **no binding row at all** — here the row *is* present, just with an empty capability, so it is not caught.
   Contrast: the `message` executor **does** require its ref (`message_name`, ~419-421) and `call` requires
   `call_pack` (~429-431). The `capability` case is missing the equivalent required-field guard.

2. **`_compose` (onboarding.py ~1005) feeds the `None` straight into the manifest:**
   ```python
   executor = {"type": "capability", "capability": b.capability_ref}   # None → CapabilityRef parse → TypeError
   ```
   `ProcessPackManifest.model_validate(...)` then hits `CapabilityRef._validate(None)` →
   `VersionedRef.parse(None)` → `TypeError: VersionedRef must be a string, got NoneType`, surfacing as an
   uncaught 500.

The same shape applies to a **human** executor whose `role` is `None` (`{"type": "human", "role": b.role}` →
`RoleId` validation fails) — guard it symmetrically while here.

## Changes

### 1 · `set_bindings` — require the ref for capability (and role for human) executors
In the per-binding loop (onboarding.py ~408), before the truthiness-gated IO lookup, add the required-field
checks so a missing ref is a **field-level 422 at the Bindings step** naming the element — matching the existing
`message`/`call` pattern and the `{"element_id", "field", "message"}` error shape already collected in `errors`:

```python
if b.executor_type == "capability":
    if not b.capability_ref:
        errors.append({"element_id": b.element_id, "field": "capability_ref",
                       "message": "capability executor requires a capability (none selected)"})
    else:
        cap_io = await self._capability_io_and_policy(b.capability_ref, s)
        if cap_io is None:
            errors.append({"element_id": b.element_id, "field": "capability_ref",
                           "message": f"capability '{b.capability_ref}' is not staged or active"})
        else:
            side_effect, floor, io_inputs, io_outputs = cap_io
            self._check_hitl_guard(b, side_effect, floor, errors)
elif b.executor_type == "message":
    ...  # unchanged
```
And for the human branch (wherever role is consumed for a human executor), add:
```python
elif b.executor_type == "human" and not b.role:
    errors.append({"element_id": b.element_id, "field": "role",
                   "message": "human executor requires a role"})
```
(Keep it consistent with how `role` is currently defaulted/inferred — only error when it is genuinely empty.)

This alone prevents the bad state from ever being saved, so the operator sees exactly which element(s) still
need a capability, at the step where they can fix it.

### 2 · `_compose` / `assemble` — defensive guard so no `None` ref can 500
Even with (1), harden the compose path so any residual missing ref (an already-saved stuck session like the one
in the logs, `assist_capability_ref`, an artifact `schema_ref`, a reused ref) yields a clean
`TransitionError(422, {...})` naming the element — never a raw `TypeError`/500. Preferred: validate before
building the manifest dict, e.g. in `_compose` accumulate the same `errors` list while iterating `s.bindings`:

```python
compose_errors: List[dict] = []
for b in s.bindings:
    if b.executor_type == "capability" and not b.capability_ref:
        compose_errors.append({"element_id": b.element_id, "field": "capability_ref",
                               "message": "capability executor has no capability bound"})
    if b.executor_type == "human" and not b.role:
        compose_errors.append({"element_id": b.element_id, "field": "role",
                               "message": "human executor has no role"})
    ...
if compose_errors:
    raise TransitionError(422, {"error": "bindings_invalid", "errors": compose_errors})
```
Then build/validate the manifest as today. (Acceptable alternative: wrap the `ProcessPackManifest.model_validate`
call in a `try/except (TypeError, ValidationError)` that re-raises as `TransitionError(422, {"error":
"manifest_invalid", "message": str(exc)})` — but the explicit pre-check gives a far better, element-named
message, so prefer it and keep the wrap only as a final backstop.) Since `assemble` (~533) and `commit` (~564)
both call `_compose`, the guard covers both entry points.

## Non-goals
- No change to inference, pre-fill (batch 2), the bijection, or manifest/contract semantics. This turns a raw
  500 into the platform's normal field-level validation error and closes the required-ref gap — nothing else.
- Not changing `VersionedRef.parse` — a `None` reaching it is the bug, not its `TypeError`.

## Definition of done
- Reproduce: an onboarding session with one capability task left `Select…` (or an un-authored decision task).
  Before: `assemble` → 500 `VersionedRef must be a string, got NoneType`. After: `set_bindings` returns **422
  `bindings_invalid`** listing that `element_id` with `field: capability_ref`; the Bindings step surfaces it
  inline (as it already renders `errors`), and the operator can never advance to a 500. If a stale session with
  a `None` ref already exists, `assemble`/`commit` now return the same clean 422 instead of a 500.
- Tests: backend — `set_bindings` with a capability binding missing `capability_ref` (and a human binding missing
  `role`) raises `TransitionError(422, bindings_invalid)` naming the element; `_compose`/`assemble` on a session
  carrying such a binding raises 422, not `TypeError`. Frontend — no change required, but confirm `BindingsStep`
  renders a per-element error for `field: capability_ref` (it already maps the `errors` array). `tsc` clean;
  onboarding tests green.
- Onboarding guide §4 Step 4 (Bindings): add a line that an unselected capability (or unauthored decision) is a
  hard validation error naming the element, not a server error. Header bumped. No ADR (bug fix + guard on
  existing semantics).
